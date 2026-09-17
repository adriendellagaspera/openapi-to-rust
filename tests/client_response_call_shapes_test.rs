use openapi_to_rust::client_generator::ClientResponseRepresentation;
use openapi_to_rust::{CodeGenerator, GeneratorConfig, SchemaAnalyzer};
use serde_json::json;
use std::path::PathBuf;

fn generator() -> CodeGenerator {
    CodeGenerator::new(GeneratorConfig {
        spec_path: PathBuf::from("fixture.json"),
        output_dir: PathBuf::from("target/response-call-shape-fixture"),
        module_name: "fixture".to_string(),
        enable_async_client: true,
        ..Default::default()
    })
}

#[test]
fn plans_multiple_response_call_shapes_without_using_rust_names_as_identity()
-> Result<(), Box<dyn std::error::Error>> {
    let spec = json!({
        "openapi": "3.1.0",
        "info": {"title": "Response Call Shapes", "version": "1.0.0"},
        "paths": {
            "/json-only": {
                "get": {
                    "operationId": "jsonOnly",
                    "responses": {
                        "200": {
                            "description": "json",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/RenderResult"}
                                }
                            }
                        }
                    }
                }
            },
            "/render": {
                "post": {
                    "operationId": "render",
                    "responses": {
                        "200": {
                            "description": "multiple representations",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/RenderResult"}
                                },
                                "audio/wav": {
                                    "schema": {"type": "string", "format": "binary"}
                                },
                                "text/event-stream": {
                                    "schema": {"type": "string"}
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
                            "description": "reserve the preferred generated suffix",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/RenderResult"}
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
                    "properties": {"id": {"type": "string"}}
                }
            }
        }
    });

    let mut analyzer = SchemaAnalyzer::new(spec)?;
    let analysis = analyzer.analyze()?;
    let generator = generator();
    let plan = generator.plan_client_call_shapes(&analysis);

    let json_only: Vec<_> = plan
        .iter()
        .filter(|shape| shape.source_operation.operation_id == "jsonOnly")
        .collect();
    assert_eq!(json_only.len(), 1);
    assert!(matches!(
        json_only[0].representation,
        ClientResponseRepresentation::Json { .. }
    ));

    let render: Vec<_> = plan
        .iter()
        .filter(|shape| shape.source_operation.operation_id == "render")
        .collect();
    assert_eq!(render.len(), 4, "{render:#?}");

    let json = render
        .iter()
        .find(|shape| {
            matches!(
                shape.representation,
                ClientResponseRepresentation::Json { .. }
            )
        })
        .expect("buffered json call shape");
    assert_eq!(json.rust_method_name, "render");
    assert_eq!(json.success_type, "RenderResult");

    let wav = render
        .iter()
        .find(|shape| {
            matches!(
                &shape.representation,
                ClientResponseRepresentation::BinaryBuffered { media_type, .. }
                    if media_type == "audio/wav"
            )
        })
        .expect("buffered wav call shape");
    assert_eq!(wav.rust_method_name, "render_wav");
    assert_eq!(wav.success_type, "bytes::Bytes");

    let wav_stream = render
        .iter()
        .find(|shape| {
            matches!(
                &shape.representation,
                ClientResponseRepresentation::BinaryStream { media_type, .. }
                    if media_type == "audio/wav"
            )
        })
        .expect("live wav call shape");
    assert_eq!(wav_stream.rust_method_name, "render_wav_stream");
    assert_eq!(wav_stream.success_type, "HttpResponseByteStream");

    let sse = render
        .iter()
        .find(|shape| {
            matches!(
                &shape.representation,
                ClientResponseRepresentation::EventStream { media_type }
                    if media_type == "text/event-stream"
            )
        })
        .expect("SSE call shape");
    assert_eq!(
        sse.rust_method_name, "render_stream_2",
        "the real renderStream operation reserves render_stream, but transport identity survives"
    );
    assert_eq!(sse.source_operation.method, "POST");
    assert_eq!(sse.source_operation.path, "/render");

    let client = generator.generate_http_client(&analysis)?;
    for method in [
        "pub async fn render(",
        "pub async fn render_wav(",
        "pub async fn render_wav_stream(",
        "pub async fn render_stream_2(",
    ] {
        assert!(client.contains(method), "missing `{method}` in:\n{client}");
    }
    Ok(())
}
