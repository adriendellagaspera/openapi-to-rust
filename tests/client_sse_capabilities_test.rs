use openapi_to_rust::{CodeGenerator, GeneratorConfig, SchemaAnalyzer};
use serde_json::json;
use std::path::PathBuf;

fn generator() -> CodeGenerator {
    CodeGenerator::new(GeneratorConfig {
        spec_path: PathBuf::from("fixture.json"),
        output_dir: PathBuf::from("target/sse-fixture"),
        module_name: "fixture".to_string(),
        enable_async_client: true,
        ..Default::default()
    })
}

#[test]
fn sse_response_uses_owned_static_stream_abi() -> Result<(), Box<dyn std::error::Error>> {
    let spec = json!({
        "openapi": "3.1.0",
        "info": {"title": "SSE Fixture", "version": "1.0.0"},
        "paths": {
            "/events": {
                "get": {
                    "operationId": "watchEvents",
                    "responses": {
                        "200": {
                            "description": "Event stream",
                            "content": {
                                "text/event-stream": {
                                    "schema": {"type": "string"}
                                }
                            }
                        }
                    }
                }
            }
        }
    });

    let mut analyzer = SchemaAnalyzer::new(spec)?;
    let analysis = analyzer.analyze()?;
    let client = generator().generate_http_client(&analysis)?;

    assert!(
        client.contains("pub type HttpResponseByteStream = futures_util::stream::BoxStream"),
        "native SSE streams must retain their Send-capable owned ABI: {client}"
    );
    assert!(
        client.contains("pub type HttpResponseByteStream = futures_util::stream::LocalBoxStream"),
        "wasm SSE streams must use the owned non-Send ABI supported by reqwest: {client}"
    );
    assert!(
        client.contains("Result<HttpResponseByteStream, ApiOpError<"),
        "SSE methods must expose the stable stream alias: {client}"
    );
    assert!(
        client.contains("Ok(Box::pin(response.bytes_stream()))"),
        "the live response stream must be boxed into the owned ABI: {client}"
    );
    assert!(
        !client.contains("impl futures_util::Stream<Item = Result<bytes::Bytes, reqwest::Error>>"),
        "SSE return types must not remain opaque: {client}"
    );
    Ok(())
}

#[test]
fn non_streaming_clients_do_not_emit_stream_alias() -> Result<(), Box<dyn std::error::Error>> {
    let spec = json!({
        "openapi": "3.1.0",
        "info": {"title": "JSON Fixture", "version": "1.0.0"},
        "paths": {
            "/value": {
                "get": {
                    "operationId": "getValue",
                    "responses": {
                        "200": {
                            "description": "JSON response",
                            "content": {
                                "application/json": {
                                    "schema": {"type": "string"}
                                }
                            }
                        }
                    }
                }
            }
        }
    });

    let mut analyzer = SchemaAnalyzer::new(spec)?;
    let analysis = analyzer.analyze()?;
    let client = generator().generate_http_client(&analysis)?;

    assert!(!client.contains("HttpResponseByteStream"));
    Ok(())
}
