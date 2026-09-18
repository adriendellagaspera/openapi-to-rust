use openapi_to_rust::{CodeGenerator, GeneratorConfig, SchemaAnalyzer};
use serde_json::json;
use std::path::PathBuf;

fn generator() -> CodeGenerator {
    CodeGenerator::new(GeneratorConfig {
        spec_path: PathBuf::from("fixture.json"),
        output_dir: PathBuf::from("target/binary-stream-fixture"),
        module_name: "fixture".to_string(),
        enable_async_client: true,
        ..Default::default()
    })
}

#[test]
fn binary_success_keeps_buffered_method_and_adds_collision_safe_stream_method()
-> Result<(), Box<dyn std::error::Error>> {
    let spec = json!({
        "openapi": "3.1.0",
        "info": {"title": "Binary Fixture", "version": "1.0.0"},
        "paths": {
            "/download": {
                "get": {
                    "operationId": "downloadFile",
                    "responses": {
                        "200": {
                            "description": "Binary response",
                            "content": {
                                "application/octet-stream": {
                                    "schema": {"type": "string", "format": "binary"}
                                }
                            }
                        }
                    }
                }
            },
            "/already-stream": {
                "get": {
                    "operationId": "downloadFileStream",
                    "responses": {
                        "200": {
                            "description": "Existing operation whose Rust name reserves the preferred suffix",
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

    assert!(
        client.contains("pub async fn download_file(")
            && client.contains("Result<bytes::Bytes, ApiOpError<"),
        "binary responses must retain the existing buffered method: {client}"
    );
    assert!(
        client.contains("pub async fn download_file_stream_2(")
            && client.contains("Result<HttpResponseByteStream, ApiOpError<"),
        "binary streaming must be additive and collision-safe: {client}"
    );
    assert!(
        client.contains("Ok(bytes::Bytes::from(body_bytes))"),
        "the buffered representation must remain bounded and materialized: {client}"
    );
    assert!(
        client.contains("Ok(Box::pin(response.bytes_stream()))"),
        "the streaming representation must return the live response body: {client}"
    );
    assert_eq!(
        client.matches("pub type HttpResponseByteStream =").count(),
        1,
        "streaming must expose exactly one public response-stream symbol: {client}"
    );
    assert!(
        client.contains("type HttpResponseByteStreamPlatform = futures_util::stream::BoxStream")
            && client.contains(
                "type HttpResponseByteStreamPlatform = futures_util::stream::LocalBoxStream"
            )
            && client.contains("pub type HttpResponseByteStream = HttpResponseByteStreamPlatform"),
        "binary streaming must preserve the portable native/wasm ABI behind one public alias: {client}"
    );
    Ok(())
}
