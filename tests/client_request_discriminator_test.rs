use openapi_to_rust::client_generator::{
    ClientRequestDiscriminatorPlan, ClientResponseRepresentation,
};
use openapi_to_rust::config::{
    ClientSection, ConfigFile, RequestDiscriminatorRule, RequestDiscriminatorTransport,
    RequestDiscriminatorValue,
};
use openapi_to_rust::{CodeGenerator, GeneratorConfig, GeneratorError, SchemaAnalyzer};
use serde_json::json;
use std::path::PathBuf;

fn spec() -> serde_json::Value {
    json!({
        "openapi": "3.1.0",
        "info": {"title": "Request discriminators", "version": "1.0.0"},
        "paths": {
            "/render": {
                "post": {
                    "operationId": "render",
                    "tags": ["rendering"],
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
                            "description": "buffered or live",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/RenderResult"}
                                },
                                "text/event-stream": {"schema": {"type": "string"}}
                            }
                        }
                    }
                }
            },
            "/other": {
                "post": {
                    "operationId": "otherRender",
                    "tags": ["rendering"],
                    "requestBody": {
                        "required": true,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/RenderRequest"}
                            }
                        }
                    },
                    "responses": {"204": {"description": "empty"}}
                }
            }
        },
        "components": {"schemas": {
            "RenderMode": {
                "type": "string",
                "enum": ["buffered-result", "live-events"],
                "x-enum-varnames": ["BufferedResult", "LiveEvents"]
            },
            "RenderRequest": {
                "type": "object",
                "required": ["live-output", "response-mode"],
                "properties": {
                    "live-output": {"type": "boolean"},
                    "response-mode": {"$ref": "#/components/schemas/RenderMode"}
                }
            },
            "RenderResult": {
                "type": "object",
                "required": ["id"],
                "properties": {"id": {"type": "string"}}
            }
        }}
    })
}

fn analyze() -> Result<openapi_to_rust::SchemaAnalysis, Box<dyn std::error::Error>> {
    let mut analyzer = SchemaAnalyzer::new(spec())?;
    Ok(analyzer.analyze()?)
}

fn rule(
    transport: RequestDiscriminatorTransport,
    media_type: &str,
    field: &str,
    value: RequestDiscriminatorValue,
) -> RequestDiscriminatorRule {
    RequestDiscriminatorRule {
        operation: "POST /render".to_string(),
        transport,
        media_type: media_type.to_string(),
        field: field.to_string(),
        value,
    }
}

fn generator(rules: Vec<RequestDiscriminatorRule>) -> CodeGenerator {
    CodeGenerator::new(GeneratorConfig {
        spec_path: PathBuf::from("fixture.json"),
        output_dir: PathBuf::from("target/request-discriminator-fixture"),
        module_name: "fixture".to_string(),
        enable_async_client: true,
        client: Some(ClientSection {
            operations: Vec::new(),
            prune_models: false,
            request_discriminators: rules,
        }),
        ..Default::default()
    })
}

fn configured_rules() -> Vec<RequestDiscriminatorRule> {
    vec![
        rule(
            RequestDiscriminatorTransport::Buffered,
            "application/json",
            "live-output",
            RequestDiscriminatorValue::Bool(false),
        ),
        rule(
            RequestDiscriminatorTransport::EventStream,
            "text/event-stream",
            "live-output",
            RequestDiscriminatorValue::Bool(true),
        ),
        rule(
            RequestDiscriminatorTransport::EventStream,
            "text/event-stream",
            "response-mode",
            RequestDiscriminatorValue::String("live-events".to_string()),
        ),
    ]
}

#[test]
fn attaches_wire_field_discriminators_to_semantic_representations()
-> Result<(), Box<dyn std::error::Error>> {
    let analysis = analyze()?;
    let generator = generator(configured_rules());
    let plans = generator.try_plan_client_call_shapes(&analysis)?;
    let render: Vec<_> = plans
        .iter()
        .filter(|plan| plan.source_operation.operation_id == "render")
        .collect();

    let json = render
        .iter()
        .find(|plan| {
            matches!(
                plan.representation,
                ClientResponseRepresentation::Json { .. }
            )
        })
        .expect("JSON call shape");
    assert_eq!(json.request_discriminators.len(), 1);
    assert_eq!(json.request_discriminators[0].wire_name, "live-output");
    assert_eq!(
        json.request_discriminators[0].value,
        RequestDiscriminatorValue::Bool(false)
    );

    let sse = render
        .iter()
        .find(|plan| {
            matches!(
                plan.representation,
                ClientResponseRepresentation::EventStream { .. }
            )
        })
        .expect("SSE call shape");
    assert_eq!(sse.request_discriminators.len(), 2);
    assert!(sse.request_discriminators.iter().any(|plan| {
        plan.wire_name == "live-output" && plan.value == RequestDiscriminatorValue::Bool(true)
    }));
    assert!(sse.request_discriminators.iter().any(|plan| {
        plan.wire_name == "response-mode"
            && plan.value == RequestDiscriminatorValue::String("live-events".to_string())
    }));

    let client = generator.generate_http_client(&analysis)?;
    let sse_start = client
        .find("pub async fn render_stream(")
        .expect("SSE method");
    let sse_body = &client[sse_start..];
    let mutation = sse_body
        .find("let mut request = request;")
        .expect("request mutation");
    let serialization = sse_body
        .find("serde_json::to_vec(&request)")
        .expect("request serialization");
    assert!(mutation < serialization);
    assert!(sse_body.contains("request.live_output"));
    assert!(sse_body.contains("request.response_mode"));
    Ok(())
}

fn assert_validation_error(rules: Vec<RequestDiscriminatorRule>, expected: &str) {
    let analysis = analyze().expect("fixture analysis");
    let error = generator(rules)
        .try_plan_client_call_shapes(&analysis)
        .expect_err("invalid discriminator must fail closed");
    let GeneratorError::ValidationError(message) = error else {
        panic!("expected validation error, got {error:?}");
    };
    assert!(message.contains(expected), "{message}");
}

#[test]
fn fails_closed_for_missing_ambiguous_or_incompatible_discriminators() {
    assert_validation_error(
        vec![rule(
            RequestDiscriminatorTransport::EventStream,
            "text/event-stream",
            "missing-wire-field",
            RequestDiscriminatorValue::Bool(true),
        )],
        "missing-wire-field",
    );

    let mut ambiguous = rule(
        RequestDiscriminatorTransport::EventStream,
        "text/event-stream",
        "live-output",
        RequestDiscriminatorValue::Bool(true),
    );
    ambiguous.operation = "tag:rendering".to_string();
    assert_validation_error(vec![ambiguous], "resolved to 2 operations");

    assert_validation_error(
        vec![rule(
            RequestDiscriminatorTransport::EventStream,
            "text/event-stream",
            "live-output",
            RequestDiscriminatorValue::String("yes".to_string()),
        )],
        "incompatible",
    );

    assert_validation_error(
        vec![rule(
            RequestDiscriminatorTransport::BinaryStream,
            "audio/wav",
            "live-output",
            RequestDiscriminatorValue::Bool(true),
        )],
        "resolved to 0 call shapes",
    );
}

#[test]
fn rejects_duplicate_discriminators_for_one_field_and_representation() {
    let duplicate = rule(
        RequestDiscriminatorTransport::EventStream,
        "text/event-stream",
        "live-output",
        RequestDiscriminatorValue::Bool(true),
    );
    assert_validation_error(
        vec![duplicate.clone(), duplicate],
        "duplicate request discriminator",
    );
}

#[test]
fn metadata_type_is_serializable_without_rust_method_semantics() {
    let plan = ClientRequestDiscriminatorPlan {
        wire_name: "live-output".to_string(),
        rust_access_path: vec!["live_output".to_string()],
        rust_value_type: "bool".to_string(),
        value: RequestDiscriminatorValue::Bool(true),
        field_required: true,
        field_nullable: false,
        field_tri_state: false,
    };
    let value = serde_json::to_value(plan).expect("serializable discriminator plan");
    assert_eq!(value["wire_name"], "live-output");
    assert!(value.get("rust_method_name").is_none());
}

#[test]
fn checked_planner_honors_configured_client_scope() -> Result<(), Box<dyn std::error::Error>> {
    let analysis = analyze()?;
    let mut config = GeneratorConfig {
        spec_path: PathBuf::from("fixture.json"),
        output_dir: PathBuf::from("target/request-discriminator-fixture"),
        module_name: "fixture".to_string(),
        enable_async_client: true,
        client: Some(ClientSection {
            operations: vec!["POST /render".to_string()],
            prune_models: false,
            request_discriminators: configured_rules(),
        }),
        ..Default::default()
    };
    config.enable_sse_client = false;
    let plans = CodeGenerator::new(config).try_plan_client_call_shapes(&analysis)?;
    assert!(!plans.is_empty());
    assert!(
        plans
            .iter()
            .all(|plan| plan.source_operation.operation_id == "render")
    );
    Ok(())
}

#[test]
fn checked_planner_rejects_discriminator_outside_client_scope() {
    let analysis = analyze().expect("fixture analysis");
    let config = GeneratorConfig {
        spec_path: PathBuf::from("fixture.json"),
        output_dir: PathBuf::from("target/request-discriminator-fixture"),
        module_name: "fixture".to_string(),
        enable_async_client: true,
        client: Some(ClientSection {
            operations: vec!["POST /other".to_string()],
            prune_models: false,
            request_discriminators: configured_rules(),
        }),
        ..Default::default()
    };
    let error = CodeGenerator::new(config)
        .try_plan_client_call_shapes(&analysis)
        .expect_err("discriminator outside selected client scope must fail closed");
    let GeneratorError::ValidationError(message) = error else {
        panic!("expected validation error, got {error:?}");
    };
    assert!(
        message.contains("not emitted by the configured client scope"),
        "{message}"
    );
}

#[test]
fn toml_config_loads_wire_level_request_discriminator() -> Result<(), Box<dyn std::error::Error>> {
    let dir = tempfile::tempdir()?;
    let spec_path = dir.path().join("spec.json");
    std::fs::write(&spec_path, serde_json::to_vec_pretty(&spec())?)?;
    let config_path = dir.path().join("openapi-to-rust.toml");
    std::fs::write(
        &config_path,
        r#"
[generator]
spec_path = "spec.json"
output_dir = "generated"
module_name = "fixture"

[features]
enable_async_client = true

[[client.request_discriminators]]
operation = "POST /render"
transport = "event_stream"
media_type = "text/event-stream"
field = "live-output"
value = true
"#,
    )?;

    let config = ConfigFile::load(&config_path)?;
    let client = config.client.expect("client config");
    assert_eq!(client.request_discriminators.len(), 1);
    let rule = &client.request_discriminators[0];
    assert_eq!(rule.operation, "POST /render");
    assert_eq!(rule.transport, RequestDiscriminatorTransport::EventStream);
    assert_eq!(rule.media_type, "text/event-stream");
    assert_eq!(rule.field, "live-output");
    assert_eq!(rule.value, RequestDiscriminatorValue::Bool(true));
    Ok(())
}
