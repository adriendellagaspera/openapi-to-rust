use openapi_to_rust::{CodeGenerator, GeneratorConfig, SchemaAnalyzer};
use serde_json::json;

#[test]
fn multiline_property_descriptions_emit_one_doc_attribute_per_line(
) -> Result<(), Box<dyn std::error::Error>> {
    let spec = json!({
        "openapi": "3.1.0",
        "info": {"title": "multiline property docs", "version": "1"},
        "paths": {},
        "components": {
            "schemas": {
                "RetryPolicy": {
                    "type": "object",
                    "properties": {
                        "jitter": {
                            "type": "number",
                            "description": "Randomize retry delay.\nKeeps synchronized clients apart."
                        }
                    }
                }
            }
        }
    });

    let mut analyzer = SchemaAnalyzer::new(spec)?;
    let mut analysis = analyzer.analyze()?;
    let generator = CodeGenerator::new(GeneratorConfig::default());
    let types = generator.generate(&mut analysis)?;

    assert!(types.contains("#[doc = \"Randomize retry delay.\"]"));
    assert!(types.contains("#[doc = \"Keeps synchronized clients apart.\"]"));
    assert!(!types.contains("Randomize retry delay.\\nKeeps synchronized clients apart."));

    Ok(())
}
