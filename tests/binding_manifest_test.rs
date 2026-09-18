use openapi_to_rust::binding_manifest::{
    BINDING_MANIFEST_FILE_NAME, BINDING_MANIFEST_SCHEMA_VERSION, BindingOperationKind,
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
                }
            }
        }
    })
}

fn generator(emit_binding_manifest: bool) -> CodeGenerator {
    CodeGenerator::new(GeneratorConfig {
        spec_path: PathBuf::from("fixture.json"),
        output_dir: PathBuf::from("target/binding-manifest-fixture"),
        module_name: "fixture".to_string(),
        emit_binding_manifest,
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
    let generator = generator(false);
    let manifest = generator.binding_manifest(&analysis)?;

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

    let render = manifest
        .operations
        .iter()
        .filter(|operation| operation.source_operation.operation_id == "render")
        .collect::<Vec<_>>();
    assert_eq!(render.len(), 4, "{render:#?}");
    assert!(render
        .iter()
        .all(|operation| operation.kind == BindingOperationKind::CallShape));
    assert!(render.iter().all(|operation| {
        operation.source_operation.method == "POST"
            && operation.source_operation.path == "/render/{item-id}"
    }));

    let json = render
        .iter()
        .find(|operation| matches!(operation.representation, ClientResponseRepresentation::Json { .. }))
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

    let first = generator.render_binding_manifest(&analysis)?;
    let second = generator.render_binding_manifest(&analysis)?;
    assert_eq!(first, second);
    assert!(first.ends_with('\n'));
    Ok(())
}

#[test]
fn opt_in_manifest_is_part_of_generation_artifacts() -> Result<(), Box<dyn std::error::Error>> {
    let mut analyzer = SchemaAnalyzer::new(spec())?;
    let mut analysis = analyzer.analyze()?;
    let generator = generator(true);
    let expected = generator.render_binding_manifest(&analysis)?;
    let result = generator.generate_all(&mut analysis)?;
    let manifest = result
        .files
        .iter()
        .find(|file| file.path == std::path::Path::new(BINDING_MANIFEST_FILE_NAME))
        .expect("binding manifest artifact");
    assert_eq!(manifest.content, expected);
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
fn config_opt_in_maps_to_generator_config() -> Result<(), Box<dyn std::error::Error>> {
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
    assert!(config.generator.binding_manifest);
    assert!(config.into_generator_config().emit_binding_manifest);
    Ok(())
}
