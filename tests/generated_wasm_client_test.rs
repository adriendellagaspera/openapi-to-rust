//! Regression gate: generated clients must compile for `wasm32-unknown-unknown`.
//!
//! The generated HTTP client buffers response bodies through
//! `__read_bounded_response_body`. It originally used `reqwest::Response::chunk()`,
//! which is native-only: reqwest's wasm backend exposes `json`/`text`/`bytes`/
//! `bytes_stream` but not `chunk`. Every generated client therefore failed to
//! build under `trunk serve` with `no method named chunk found for struct
//! Response` (issue #74).
//!
//! This test generates a client that exercises the buffered success, buffered
//! error, binary, and auto-detected SSE paths, then `cargo check`s the exact
//! `REQUIRED_DEPS.toml` output for wasm32. It is the only automated check that
//! would have caught the regression, so it belongs on CI.
//!
//! The opt-in SSE runtime (`enable_sse_client` + `[[streaming.endpoints]]`) is
//! intentionally out of scope: it builds `Send` futures and `Pin<Box<dyn
//! Stream + Send>>`, which cannot satisfy wasm32's single-threaded `fetch`.
//! That is tracked separately.
//!
//! The `wasm32-unknown-unknown` target must be installed. The test skips (with
//! a printed notice) when it is absent so it cannot fail a machine that simply
//! lacks the target; CI installs it explicitly.
//!
//! `cargo check` for wasm32 still resolves reqwest's wasm backend and the
//! `stream` feature, so a genuinely bad generated call is a compile error here
//! rather than a silent pass.

use openapi_to_rust::http_config::HttpClientConfig;
use openapi_to_rust::{CodeGenerator, GeneratorConfig, SchemaAnalyzer};
use serde_json::json;
use std::collections::HashMap;
use std::process::Command;

/// A spec touching every place the bounded buffering helper is emitted:
/// buffered JSON, buffered text, buffered binary, an error body, and an
/// auto-detected `text/event-stream` response.
fn wasm_client_spec() -> serde_json::Value {
    json!({
        "openapi": "3.1.0",
        "info": { "title": "wasm client", "version": "1.0.0" },
        "paths": {
            "/json": { "get": {
                "operationId": "getJson",
                "responses": {
                    "200": { "description": "ok", "content": { "application/json": {
                        "schema": { "$ref": "#/components/schemas/Thing" }
                    }}},
                    "400": { "description": "err", "content": { "application/json": {
                        "schema": { "$ref": "#/components/schemas/Thing" }
                    }}}
                }
            }},
            "/text": { "get": {
                "operationId": "getText",
                "responses": {
                    "200": { "description": "ok", "content": { "text/plain": {
                        "schema": { "type": "string" }
                    }}}
                }
            }},
            "/binary": { "get": {
                "operationId": "getBinary",
                "responses": {
                    "200": { "description": "ok", "content": { "application/octet-stream": {
                        "schema": { "type": "string", "format": "binary" }
                    }}}
                }
            }},
            "/events": { "get": {
                "operationId": "streamEvents",
                "responses": {
                    "200": { "description": "events", "content": { "text/event-stream": {
                        "schema": { "$ref": "#/components/schemas/Thing" }
                    }}}
                }
            }}
        },
        "components": { "schemas": {
            "Thing": {
                "type": "object",
                "required": ["id"],
                "properties": { "id": { "type": "string" }, "name": { "type": "string" } }
            }
        }}
    })
}

/// True when the wasm32 standard library is present in the active sysroot.
/// `rustup target list --installed` is the authoritative source, but this
/// avoids assuming the toolchain is rustup-managed.
fn wasm32_target_installed() -> bool {
    let output = Command::new("rustc")
        .args([
            "--print",
            "target-libdir",
            "--target",
            "wasm32-unknown-unknown",
        ])
        .output();
    let Ok(output) = output else {
        return false;
    };
    if !output.status.success() {
        return false;
    }
    let libdir = String::from_utf8_lossy(&output.stdout);
    // A missing target yields the path but not the `lib` directory.
    std::path::Path::new(libdir.trim()).is_dir()
}

#[test]
fn generated_client_compiles_for_wasm32() {
    if !wasm32_target_installed() {
        eprintln!(
            "skipping: wasm32-unknown-unknown target not installed \
             (run `rustup target add wasm32-unknown-unknown`)"
        );
        return;
    }

    // Default configuration: `tracing_enabled` is true by default and pulls in
    // reqwest-tracing, so the real default stack is what gets checked.
    //
    // Two opt-in stacks are deliberately out of scope and tracked separately,
    // because neither is wasm32-compatible for reasons outside this helper:
    //   * the SSE runtime (`enable_sse_client` + `[[streaming.endpoints]]`)
    //     builds `Send` futures and `Pin<Box<dyn Stream + Send>>`;
    //   * retry (`[http_client.retry]`) pulls `retry-policies` -> `rand` ->
    //     `getrandom 0.4`, which rejects wasm32 without `wasm_js`.
    let temp = tempfile::TempDir::new().unwrap();
    let output_dir = temp.path().join("src/generated");

    let mut analysis = SchemaAnalyzer::new(wasm_client_spec())
        .unwrap()
        .analyze()
        .unwrap();
    let generator = CodeGenerator::new(GeneratorConfig {
        output_dir: output_dir.clone(),
        module_name: "generated".into(),
        enable_async_client: true,
        // No `[streaming]` config: this exercises the plain client plus the
        // auto-detected SSE operation, whose error path also buffers through
        // the helper.
        enable_sse_client: false,
        tracing_enabled: true,
        http_client_config: Some(HttpClientConfig {
            base_url: None,
            timeout_seconds: None,
            max_response_body_bytes: Some(8),
            default_headers: HashMap::new(),
        }),
        ..Default::default()
    });
    let result = generator.generate_all(&mut analysis).unwrap();
    generator.write_files(&result).unwrap();

    // The generated client module is mounted at src/generated; the crate root
    // is just a re-export shim. `dead_code` is expected in a spec-covering
    // compile check.
    std::fs::write(
        temp.path().join("src/lib.rs"),
        "#![allow(dead_code, unused_imports)]\npub mod generated;\n",
    )
    .unwrap();

    let dependencies = std::fs::read_to_string(output_dir.join("REQUIRED_DEPS.toml"))
        .expect("generated REQUIRED_DEPS.toml");
    std::fs::write(
        temp.path().join("Cargo.toml"),
        format!(
            "[workspace]\n\n\
             [package]\n\
             name = \"wasm-client-check\"\n\
             version = \"0.0.0\"\n\
             edition = \"2024\"\n\
             publish = false\n\n\
             {dependencies}"
        ),
    )
    .unwrap();

    // Keep the check cheap: reuse one workspace target dir across runs so
    // reqwest's wasm backend is compiled once. The scratch crate has no lock
    // file, so allow the resolver to reach the index on a cold cache rather
    // than passing `--offline`.
    let manifest_dir =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("target/generated-wasm32-client");
    let output = Command::new("cargo")
        .args([
            "check",
            "--lib",
            "--quiet",
            "--target",
            "wasm32-unknown-unknown",
        ])
        .current_dir(temp.path())
        .env("CARGO_TARGET_DIR", manifest_dir)
        .output()
        .expect("cargo check runs");

    assert!(
        output.status.success(),
        "generated client failed to compile for wasm32-unknown-unknown (issue #74):\n{}",
        String::from_utf8_lossy(&output.stderr)
    );
}
