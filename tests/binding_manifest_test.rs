use openapi_to_rust::binding_manifest::{
    BINDING_MANIFEST_FILE_NAME, BINDING_MANIFEST_SCHEMA, BINDING_MANIFEST_SCHEMA_VERSION,
    BindingOperationKind,
};
use openapi_to_rust::client_generator::ClientResponseRepresentation;
use openapi_to_rust::config::{
    ClientSection, ConfigFile, RequestDiscriminatorRule, RequestDiscriminatorTransport,
    RequestDiscriminatorValue,
};
use openapi_to_rust::{CodeGenerator, GeneratorConfig, SchemaAnalyzer};
use serde_json::json;
use std::path::PathBuf;

fn spec() -> serde_json::Value {
    json!({
        "openapi": "3.1.0",
        "info": {"title": "Binding manifest", "version": "1.0.0"},
        "paths": {
            "/render/{item-id}": {
                "post": {
                    "operationId": "render",
                    "parameters": [
                        {
                            "name": "item-id",
                            "in": "path",
                            "required": true,
                            "schema": {"type": "string"}
                        },
                        {
                            "name": "limit",
                            "in": "query",
                            "required": false,
                            "schema": {"type": "integer"}
                        }
                    ],
                    "requestBody": {
                        "required": true,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/RenderRequest"}
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "multiple representations",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/RenderResult"}
                                },
                                "text/event-stream": {"schema": {"type": "string"}},
                                "audio/wav": {
                                    "schema": {"type": "string", "format": "binary"}
                                }
                            }
                        }
                    }
                }
            },
            "/reserved-stream-name": {
                "get": {
                    "operationId": "renderStream",
                    "responses": {
                        "200": {
                            "description": "reserve the preferred SSE suffix",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/RenderResult"}
                                }
                            }
                        }
                    }
                }
            },
            "/health": {
                "get": {
                    "operationId": "healthCheck",
                    "responses": {
                        "204": {"description": "empty"}
                    }
                }
            }
        },
        "components": {
            "schemas": {
                "Identifier": {"type": "string"},
                "RenderMode": {
                    "type": "string",
                    "enum": ["buffered-result", "live-events"],
                    "x-enum-varnames": ["BufferedResult", "LiveEvents"]
                },
                "RenderRequest": {
                    "type": "object",
                    "required": ["live-output", "type"],
                    "properties": {
                        "live-output": {"type": "boolean"},
                        "type": {"type": "string"},
                        "mode": {"$ref": "#/components/schemas/RenderMode"}
                    }
                },
                "RenderResult": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {
                        "id": {"$ref": "#/components/schemas/Identifier"}
                    }
                },
                "Cat": {
                    "type": "object",
                    "required": ["kind"],
                    "properties": {
                        "kind": {"type": "string", "enum": ["cat"]}
                    }
                },
                "Dog": {
                    "type": "object",
                    "required": ["kind"],
                    "properties": {
                        "kind": {"type": "string", "enum": ["dog"]}
                    }
                },
                "Animal": {
                    "oneOf": [
                        {"$ref": "#/components/schemas/Cat"},
                        {"$ref": "#/components/schemas/Dog"}
                    ],
                    "discriminator": {
                        "propertyName": "kind",
                        "mapping": {
                            "cat": "#/components/schemas/Cat",
                            "dog": "#/components/schemas/Dog"
                        }
                    }
                }
            }
        }
    })
}

fn generator() -> CodeGenerator {
    CodeGenerator::new(GeneratorConfig {
        spec_path: PathBuf::from("fixture.json"),
        output_dir: PathBuf::from("target/binding-manifest-fixture"),
        module_name: "fixture".to_string(),
        enable_async_client: true,
        client: Some(ClientSection {
            operations: Vec::new(),
            prune_models: false,
            request_discriminators: vec![RequestDiscriminatorRule {
                operation: "POST /render/{item-id}".to_string(),
                transport: RequestDiscriminatorTransport::EventStream,
                media_type: "text/event-stream".to_string(),
                field: "live-output".to_string(),
                value: RequestDiscriminatorValue::Bool(true),
            }],
        }),
        ..Default::default()
    })
}

#[test]
fn manifest_carries_shared_model_and_operation_plans() -> Result<(), Box<dyn std::error::Error>> {
    let mut analyzer = SchemaAnalyzer::new(spec())?;
    let analysis = analyzer.analyze()?;
    let generator = generator();
    let manifest = generator.binding_manifest(&analysis)?;

    assert_eq!(manifest.schema, BINDING_MANIFEST_SCHEMA);
    assert_eq!(manifest.schema_version, BINDING_MANIFEST_SCHEMA_VERSION);
    assert_eq!(manifest.generator.name, "openapi-to-rust");
    assert_eq!(manifest.aliases["Identifier"], "String");
    assert_eq!(manifest.symbol_paths["Identifier"], "types::Identifier");

    let request = &manifest.structs["RenderRequest"];
    assert!(request.iter().any(|field| {
        field.name == "live_output"
            && field.wire_name.as_deref() == Some("live-output")
            && field.type_name == "bool"
    }));
    assert!(request.iter().any(|field| {
        field.name == "r#type"
            && field.wire_name.as_deref() == Some("type")
            && field.type_name == "String"
    }));
    assert!(request.iter().any(|field| {
        field.name == "mode"
            && field.wire_name.as_deref() == Some("mode")
            && field.type_name == "Option<RenderMode>"
    }));

    let mode = &manifest.enums["RenderMode"];
    assert_eq!(mode[0].name, "BufferedResult");
    assert_eq!(mode[0].wire_name.as_deref(), Some("buffered-result"));
    assert_eq!(mode[1].name, "LiveEvents");
    assert_eq!(mode[1].wire_name.as_deref(), Some("live-events"));

    let animal = &manifest.enums["Animal"];
    let animal_wire_names = animal
        .iter()
        .filter_map(|variant| variant.wire_name.as_deref())
        .collect::<std::collections::BTreeSet<_>>();
    assert_eq!(
        animal_wire_names,
        std::collections::BTreeSet::from(["cat", "dog"])
    );

    let render = manifest
        .operations
        .iter()
        .filter(|operation| operation.source_operation.operation_id == "render")
        .collect::<Vec<_>>();
    assert_eq!(render.len(), 4, "{render:#?}");
    assert!(
        render
            .iter()
            .all(|operation| operation.kind == BindingOperationKind::CallShape)
    );
    assert!(render.iter().all(|operation| {
        operation.source_operation.method == "POST"
            && operation.source_operation.path == "/render/{item-id}"
    }));

    let json = render
        .iter()
        .find(|operation| {
            matches!(
                operation.representation,
                ClientResponseRepresentation::Json { .. }
            )
        })
        .expect("JSON operation");
    assert_eq!(
        json.parameters
            .iter()
            .map(|parameter| (parameter.name.as_str(), parameter.type_name.as_str()))
            .collect::<Vec<_>>(),
        vec![
            ("item_id", "impl AsRef<str>"),
            ("limit", "Option<i64>"),
            ("request", "RenderRequest"),
        ]
    );
    assert_eq!(json.success_type, "RenderResult");
    assert!(json.return_type.contains("ApiOpError<"));
    assert!(json.stream.is_none());

    let sse = render
        .iter()
        .find(|operation| {
            matches!(
                &operation.representation,
                ClientResponseRepresentation::EventStream { media_type }
                    if media_type == "text/event-stream"
            )
        })
        .expect("SSE operation");
    assert_eq!(
        sse.rust_method_name, "render_stream_2",
        "the real renderStream operation must reserve render_stream without changing source identity"
    );
    assert_eq!(sse.source_operation.operation_id, "render");
    assert_eq!(sse.success_type, "HttpResponseByteStream");
    assert_eq!(sse.request_discriminators.len(), 1);
    let stream = sse.stream.as_ref().expect("stream ABI");
    assert_eq!(stream.item_type, "bytes::Bytes");
    assert_eq!(stream.error_type, "reqwest::Error");
    assert_eq!(stream.lifetime, "'static");

    assert!(render.iter().any(|operation| {
        matches!(
            &operation.representation,
            ClientResponseRepresentation::BinaryBuffered { media_type, .. }
                if media_type == "audio/wav"
        )
    }));
    assert!(render.iter().any(|operation| {
        matches!(
            &operation.representation,
            ClientResponseRepresentation::BinaryStream { media_type, .. }
                if media_type == "audio/wav"
        )
    }));

    let health = manifest
        .operations
        .iter()
        .find(|operation| operation.source_operation.operation_id == "healthCheck")
        .expect("empty response operation");
    assert!(matches!(
        health.representation,
        ClientResponseRepresentation::Empty
    ));
    assert_eq!(health.success_type, "()");
    assert!(health.return_type.starts_with("Result<(), ApiOpError<"));

    let first = generator.render_binding_manifest(&analysis)?;
    let second = generator.render_binding_manifest(&analysis)?;
    assert_eq!(first, second);
    assert!(first.ends_with('\n'));
    Ok(())
}

#[test]
fn manifest_api_is_additive_to_generation_result() -> Result<(), Box<dyn std::error::Error>> {
    let mut analyzer = SchemaAnalyzer::new(spec())?;
    let mut analysis = analyzer.analyze()?;
    let generator = generator();
    let manifest = generator.render_binding_manifest(&analysis)?;
    let result = generator.generate_all(&mut analysis)?;
    assert!(manifest.contains("\"schema_version\": 1"));
    assert!(
        result
            .files
            .iter()
            .all(|file| file.path != std::path::Path::new(BINDING_MANIFEST_FILE_NAME))
    );
    assert!(
        result
            .mod_file
            .content
            .lines()
            .all(|line| !line.contains("binding-manifest"))
    );
    Ok(())
}

#[test]
fn config_opt_in_is_accepted_without_changing_public_config_shapes()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    let spec_path = directory.path().join("spec.json");
    std::fs::write(&spec_path, serde_json::to_vec_pretty(&spec())?)?;
    let config_path = directory.path().join("openapi-to-rust.toml");
    std::fs::write(
        &config_path,
        r#"
[generator]
spec_path = "spec.json"
output_dir = "generated"
module_name = "fixture"
binding_manifest = true

[features]
enable_async_client = true
"#,
    )?;
    let config = ConfigFile::load(&config_path)?;
    let _generator_config = config.into_generator_config();
    Ok(())
}

#[test]
fn manifest_honors_client_scope() -> Result<(), Box<dyn std::error::Error>> {
    let mut analyzer = SchemaAnalyzer::new(spec())?;
    let analysis = analyzer.analyze()?;
    let generator = CodeGenerator::new(GeneratorConfig {
        enable_async_client: true,
        client: Some(ClientSection {
            operations: vec!["healthCheck".to_string()],
            prune_models: false,
            request_discriminators: Vec::new(),
        }),
        ..Default::default()
    });
    let manifest = generator.binding_manifest(&analysis)?;
    assert_eq!(manifest.operations.len(), 1, "{:#?}", manifest.operations);
    assert_eq!(
        manifest.operations[0].source_operation.operation_id,
        "healthCheck"
    );
    Ok(())
}

#[test]
fn manifest_rejects_absent_raw_client() -> Result<(), Box<dyn std::error::Error>> {
    let mut analyzer = SchemaAnalyzer::new(spec())?;
    let analysis = analyzer.analyze()?;
    let generator = CodeGenerator::new(GeneratorConfig {
        enable_async_client: false,
        ..Default::default()
    });
    let error = generator
        .binding_manifest(&analysis)
        .expect_err("manifest must not describe a client that was not emitted");
    assert!(
        error
            .to_string()
            .contains("requires emitted model types and the async HTTP client")
    );
    Ok(())
}

#[test]
fn cli_opt_in_emits_checks_and_dry_runs_manifest() -> Result<(), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    let spec_path = directory.path().join("spec.json");
    std::fs::write(&spec_path, serde_json::to_vec_pretty(&spec())?)?;
    let config_path = directory.path().join("openapi-to-rust.toml");
    std::fs::write(
        &config_path,
        r#"
[generator]
spec_path = "spec.json"
output_dir = "generated"
module_name = "fixture"
binding_manifest = true

[features]
enable_async_client = true
"#,
    )?;

    let binary = env!("CARGO_BIN_EXE_openapi-to-rust");
    let generated = std::process::Command::new(binary)
        .arg("generate")
        .arg("--config")
        .arg(&config_path)
        .arg("--quiet")
        .output()?;
    assert!(
        generated.status.success(),
        "{}",
        String::from_utf8_lossy(&generated.stderr)
    );
    assert!(
        directory
            .path()
            .join("generated")
            .join(BINDING_MANIFEST_FILE_NAME)
            .is_file()
    );

    let checked = std::process::Command::new(binary)
        .arg("generate")
        .arg("--config")
        .arg(&config_path)
        .arg("--check")
        .arg("--quiet")
        .output()?;
    assert!(
        checked.status.success(),
        "{}",
        String::from_utf8_lossy(&checked.stderr)
    );

    let dry_run = std::process::Command::new(binary)
        .arg("generate")
        .arg("--config")
        .arg(&config_path)
        .arg("--dry-run")
        .arg("--json")
        .output()?;
    assert!(
        dry_run.status.success(),
        "{}",
        String::from_utf8_lossy(&dry_run.stderr)
    );
    let summary: serde_json::Value = serde_json::from_slice(&dry_run.stdout)?;
    assert_eq!(summary["status"], "dry-run");
    assert!(
        summary["files"]
            .as_array()
            .is_some_and(|files| files.iter().any(|file| file == BINDING_MANIFEST_FILE_NAME))
    );
    Ok(())
}
