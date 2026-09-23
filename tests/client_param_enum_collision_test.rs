use openapi_to_rust::{CodeGenerator, GeneratorConfig, SchemaAnalyzer};
use serde_json::json;

#[test]
fn parameter_enum_collision_suffixes_stay_pascal_case() -> Result<(), Box<dyn std::error::Error>> {
    let spec = json!({
        "openapi": "3.1.0",
        "info": {"title": "parameter enum collisions", "version": "1"},
        "paths": {
            "/jobs": {
                "get": {
                    "operationId": "listJobs",
                    "parameters": [{
                        "name": "order_by",
                        "in": "query",
                        "required": false,
                        "schema": {
                            "type": "string",
                            "enum": ["created", "-created"]
                        }
                    }],
                    "responses": {
                        "204": {"description": "ok"}
                    }
                }
            }
        }
    });
    let mut analyzer = SchemaAnalyzer::new(spec)?;
    let analysis = analyzer.analyze()?;
    let generator = CodeGenerator::new(GeneratorConfig {
        enable_async_client: true,
        ..Default::default()
    });

    let client = generator.generate_http_client(&analysis)?;
    assert!(client.contains("#[serde(rename = \"created\")]\n    Created,"));
    assert!(client.contains("#[serde(rename = \"-created\")]\n    Created2,"));
    assert!(!client.contains("Created_2"));
    Ok(())
}
