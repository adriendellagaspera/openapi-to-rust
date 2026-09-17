use openapi_to_rust::{CodeGenerator, GeneratorConfig, SchemaAnalyzer};
use serde_json::json;
use std::process::Command;

#[test]
fn generated_sse_success_stream_is_static() {
    let spec = json!({
        "openapi": "3.1.0",
        "info": { "title": "owned SSE fixture", "version": "1.0.0" },
        "paths": {
            "/events": {
                "get": {
                    "operationId": "getEvents",
                    "responses": {
                        "200": {
                            "description": "events",
                            "content": {
                                "text/event-stream": {
                                    "schema": { "type": "string" }
                                }
                            }
                        }
                    }
                }
            }
        }
    });

    let temp = tempfile::TempDir::new().unwrap();
    let output_dir = temp.path().join("src/generated");
    let mut analysis = SchemaAnalyzer::new(spec).unwrap().analyze().unwrap();
    let generator = CodeGenerator::new(GeneratorConfig {
        output_dir: output_dir.clone(),
        enable_async_client: true,
        enable_sse_client: false,
        tracing_enabled: false,
        ..Default::default()
    });
    let result = generator.generate_all(&mut analysis).unwrap();
    generator.write_files(&result).unwrap();

    let client = result
        .files
        .iter()
        .find(|file| file.path == std::path::Path::new("client.rs"))
        .expect("generated client.rs");
    assert!(
        client.content.contains(
            "impl futures_util::Stream<Item = Result<bytes::Bytes, reqwest::Error>> + 'static"
        ),
        "generated SSE ABI must explicitly promise an owned static stream: {}",
        client.content
    );

    std::fs::write(
        temp.path().join("src/lib.rs"),
        r#"pub mod generated;

use generated::client::HttpClient;

fn require_static<T: 'static>(_: &T) {}

#[allow(dead_code)]
async fn sse_stream_does_not_borrow_client(client: &HttpClient) {
    let stream = client.get_events().await.unwrap();
    require_static(&stream);
}
"#,
    )
    .unwrap();

    let dependencies = std::fs::read_to_string(output_dir.join("REQUIRED_DEPS.toml")).unwrap();
    std::fs::write(
        temp.path().join("Cargo.toml"),
        format!(
            r#"[package]
name = "owned-static-sse-client"
version = "0.0.0"
edition = "2024"
publish = false

{dependencies}
"#
        ),
    )
    .unwrap();

    let output = Command::new("cargo")
        .args(["check", "--quiet"])
        .current_dir(temp.path())
        .env("CARGO_BUILD_BUILD_DIR", temp.path().join("cargo-build"))
        .env("CARGO_TARGET_DIR", temp.path().join("cargo-target"))
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "generated SSE client failed static ABI typecheck:\nstdout: {}\nstderr: {}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}
