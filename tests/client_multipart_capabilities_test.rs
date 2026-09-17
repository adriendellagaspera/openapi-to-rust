use openapi_to_rust::{CodeGenerator, GeneratorConfig, SchemaAnalyzer};
use serde_json::json;
use std::path::PathBuf;

#[test]
fn repeated_scalar_fields_and_nullable_binary_parts_generate_typed_multipart()
-> Result<(), Box<dyn std::error::Error>> {
    let spec = json!({
        "openapi": "3.1.0",
        "info": {"title": "Multipart Fixture", "version": "1.0.0"},
        "paths": {
            "/uploads": {
                "post": {
                    "operationId": "createUpload",
                    "requestBody": {
                        "required": true,
                        "content": {
                            "multipart/form-data": {
                                "schema": {"$ref": "#/components/schemas/UploadRequest"}
                            }
                        }
                    },
                    "responses": {"204": {"description": "Uploaded"}}
                }
            }
        },
        "components": {
            "schemas": {
                "Mode": {
                    "type": "string",
                    "enum": ["fast", "safe"]
                },
                "File": {
                    "type": "string",
                    "format": "binary"
                },
                "UploadRequest": {
                    "type": "object",
                    "required": ["labels", "file", "thumbnail"],
                    "properties": {
                        "labels": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "modes": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/Mode"}
                        },
                        "file": {
                            "anyOf": [
                                {"$ref": "#/components/schemas/File"},
                                {"type": "null"}
                            ]
                        },
                        "thumbnail": {"$ref": "#/components/schemas/File"}
                    }
                }
            }
        }
    });

    let mut analyzer = SchemaAnalyzer::new(spec)?;
    let analysis = analyzer.analyze()?;
    let generator = CodeGenerator::new(GeneratorConfig {
        spec_path: PathBuf::from("fixture.json"),
        output_dir: PathBuf::from("target/multipart-fixture"),
        module_name: "fixture".to_string(),
        enable_async_client: true,
        ..Default::default()
    });
    let client = generator.generate_http_client(&analysis)?;

    assert!(
        !client.contains("must be binary or a scalar text field"),
        "{client}"
    );
    assert!(
        client.contains("form = form.text(\"labels\", item.to_string());"),
        "required string arrays must use repeated multipart fields: {client}"
    );
    assert!(
        client.contains("form = form.text(\"modes\", item.to_string());"),
        "enum arrays must use repeated multipart fields: {client}"
    );
    assert!(
        client.contains("pub async fn create_upload_with_multipart_filenames"),
        "multipart operations must expose a per-call filename variant: {client}"
    );
    assert!(
        client.contains("multipart_filenames: &[(&str, &str)]"),
        "filename overrides must be request-local rather than client state: {client}"
    );
    assert!(
        client.contains("*field == \"file\"") && client.contains("*field == \"thumbnail\""),
        "each binary field must resolve its own filename override: {client}"
    );
    assert!(
        client.contains("unwrap_or_else(|| \"file\".to_string())")
            && client.contains("unwrap_or_else(|| \"thumbnail\".to_string())"),
        "unconfigured binary fields need deterministic field-local fallbacks: {client}"
    );
    Ok(())
}
