use openapi_to_rust::SchemaAnalyzer;
use openapi_to_rust::analysis::OperationResponseRepresentation;
use serde_json::json;

#[test]
fn retains_alternate_response_transport_representations() {
    let spec = json!({
        "openapi": "3.1.0",
        "info": { "title": "Representations", "version": "1.0.0" },
        "paths": {
            "/render": {
                "post": {
                    "operationId": "render",
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": { "$ref": "#/components/schemas/RenderResult" }
                                },
                                "audio/wav": {
                                    "schema": { "type": "string", "format": "binary" }
                                },
                                "text/event-stream": {
                                    "schema": { "type": "string" }
                                }
                            }
                        }
                    }
                }
            }
        },
        "components": {
            "schemas": {
                "RenderResult": {
                    "type": "object",
                    "required": ["id"],
                    "properties": { "id": { "type": "string" } }
                }
            }
        }
    });

    let mut analyzer = SchemaAnalyzer::new(spec).expect("valid fixture");
    let analysis = analyzer.analyze().expect("analysis succeeds");
    let response = analysis
        .operation_responses
        .get("render")
        .and_then(|responses| responses.get("200"))
        .expect("200 response");

    assert!(
        response
            .representations
            .iter()
            .any(|representation| matches!(
                representation,
                OperationResponseRepresentation::Json { schema_name, media_type }
                    if schema_name == "RenderResult" && media_type == "application/json"
            ))
    );
    assert!(
        response
            .representations
            .iter()
            .any(|representation| matches!(
                representation,
                OperationResponseRepresentation::Binary { media_type, wildcard: false }
                    if media_type == "audio/wav"
            ))
    );
    assert!(
        response
            .representations
            .iter()
            .any(|representation| matches!(
                representation,
                OperationResponseRepresentation::EventStream { media_type }
                    if media_type == "text/event-stream"
            ))
    );
}
