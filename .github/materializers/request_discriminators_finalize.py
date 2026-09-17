from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"missing replacement anchor in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1))


# The checked planner is intended for binding metadata, so it must use the
# exact same configured operation scope as the source renderer.
replace_once(
    "src/generator.rs",
    "    fn resolve_client_operation_ids(\n",
    "    pub(crate) fn resolve_client_operation_ids(\n",
)
replace_once(
    "src/generator.rs",
    "    fn client_operations<'a>(\n",
    "    pub(crate) fn client_operations<'a>(\n",
)
replace_once(
    "src/client_generator.rs",
    '''    pub fn try_plan_client_call_shapes(
        &self,
        analysis: &SchemaAnalysis,
    ) -> crate::Result<Vec<ClientCallShapePlan>> {
        let operations: Vec<&OperationInfo> = analysis.operations.values().collect();
        self.validate_client_request_discriminators(analysis, &operations)?;
        Ok(self
            .plan_client_operation_methods(analysis, &operations)
            .into_iter()
            .flat_map(|plan| plan.call_shapes)
            .collect())
    }
''',
    '''    pub fn try_plan_client_call_shapes(
        &self,
        analysis: &SchemaAnalysis,
    ) -> crate::Result<Vec<ClientCallShapePlan>> {
        let client_ids = self.resolve_client_operation_ids(analysis)?;
        let operations = self.client_operations(analysis, client_ids.as_ref());
        self.validate_client_request_discriminators(analysis, &operations)?;
        Ok(self
            .plan_client_operation_methods(analysis, &operations)
            .into_iter()
            .flat_map(|plan| plan.call_shapes)
            .collect())
    }
''',
)

# Add configuration-load and scoped-planner regressions to the focused fixture.
test = Path("tests/client_request_discriminator_test.rs")
text = test.read_text()
text = text.replace(
    "use openapi_to_rust::config::{\n",
    "use openapi_to_rust::config::{\n    ConfigFile,\n",
    1,
)
text += r'''

#[test]
fn checked_planner_honors_configured_client_scope()
-> Result<(), Box<dyn std::error::Error>> {
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
    assert!(plans.iter().all(|plan| plan.source_operation.operation_id == "render"));
    Ok(())
}

#[test]
fn toml_config_loads_wire_level_request_discriminator()
-> Result<(), Box<dyn std::error::Error>> {
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
'''
test.write_text(text)
