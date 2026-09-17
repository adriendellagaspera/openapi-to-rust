from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text()
    if old not in text:
        raise SystemExit(f"expected anchor missing from {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1))


def append(path: str, text: str) -> None:
    target = ROOT / path
    current = target.read_text()
    if text.strip() in current:
        return
    target.write_text(current.rstrip() + "\n\n" + text.lstrip())


replace(
    "Cargo.toml",
    'jsonschema = { version = "0.49", default-features = false }\nregex = "1"\n',
    'jsonschema = { version = "0.49", default-features = false }\njsonpath-rust = "=1.0.10"\nregex = "1"\n',
)

replace(
    "src/lib.rs",
    "pub mod openapi;\npub mod patterns;\n",
    "pub mod openapi;\npub mod overlay;\npub mod patterns;\n",
)
replace(
    "src/lib.rs",
    "pub use openapi::{OpenApiSpec, Schema, SchemaType};\n",
    "pub use openapi::{OpenApiSpec, Schema, SchemaType};\npub use overlay::{OverlayError, apply_overlay, apply_overlay_file, apply_overlay_files, materialize_document};\n",
)

# Generator config: repo/config-relative Overlay files and deterministic output path.
replace(
    "src/config.rs",
    '    /// Schema extension files to merge into the main spec before codegen.\n    /// Relative paths are resolved from the configuration file\'s directory.\n    #[serde(default)]\n    pub schema_extensions: Vec<PathBuf>,\n    /// Additive operation-builder generation policy.\n',
    '    /// Schema extension files to merge into the main spec before codegen.\n    /// Relative paths are resolved from the configuration file\'s directory.\n    #[serde(default)]\n    pub schema_extensions: Vec<PathBuf>,\n    /// OpenAPI Overlay 1.1 files applied in order before analysis/codegen.\n    /// Relative paths are resolved from the configuration file\'s directory.\n    #[serde(default)]\n    pub overlays: Vec<PathBuf>,\n    /// Deterministic JSON materialization of the overlaid OpenAPI document.\n    /// Relative paths are resolved from the configuration file\'s directory.\n    #[serde(default)]\n    pub overlay_output: Option<PathBuf>,\n    /// Additive operation-builder generation policy.\n',
)
replace(
    "src/config.rs",
    '    #[serde(default)]\n    schema_extensions: Vec<PathBuf>,\n    #[serde(default)]\n    builders: BuildersSection,\n',
    '    #[serde(default)]\n    schema_extensions: Vec<PathBuf>,\n    #[serde(default)]\n    overlays: Vec<PathBuf>,\n    #[serde(default)]\n    overlay_output: Option<PathBuf>,\n    #[serde(default)]\n    builders: BuildersSection,\n',
)
replace(
    "src/config.rs",
    '                schema_extensions: wire.generator.schema_extensions,\n                builders: wire.generator.builders,\n',
    '                schema_extensions: wire.generator.schema_extensions,\n                overlays: wire.generator.overlays,\n                overlay_output: wire.generator.overlay_output,\n                builders: wire.generator.builders,\n',
)
replace(
    "src/config.rs",
    "    schema_extensions: &'a [PathBuf],\n    builders: &'a BuildersSection,\n",
    "    schema_extensions: &'a [PathBuf],\n    overlays: &'a [PathBuf],\n    #[serde(skip_serializing_if = \"Option::is_none\")]\n    overlay_output: Option<&'a PathBuf>,\n    builders: &'a BuildersSection,\n",
)
replace(
    "src/config.rs",
    '                schema_extensions: &self.generator.schema_extensions,\n                builders: &self.generator.builders,\n',
    '                schema_extensions: &self.generator.schema_extensions,\n                overlays: &self.generator.overlays,\n                overlay_output: self.generator.overlay_output.as_ref(),\n                builders: &self.generator.builders,\n',
)
replace(
    "src/config.rs",
    '        for extension in &mut config.generator.schema_extensions {\n            resolve_relative_path(config_dir, extension);\n        }\n\n        config.validate()?;\n',
    '        for extension in &mut config.generator.schema_extensions {\n            resolve_relative_path(config_dir, extension);\n        }\n        for overlay in &mut config.generator.overlays {\n            resolve_relative_path(config_dir, overlay);\n        }\n        if let Some(output) = &mut config.generator.overlay_output {\n            resolve_relative_path(config_dir, output);\n        }\n\n        config.validate()?;\n',
)
replace(
    "src/config.rs",
    '        if self.generator.module_name.is_empty() {\n',
    '        for (index, overlay) in self.generator.overlays.iter().enumerate() {\n            if !overlay.is_file() {\n                errors.push(format!(\n                    "generator.overlays[{index}]: Overlay file not found: {}",\n                    overlay.display()\n                ));\n            }\n        }\n        if !self.generator.overlays.is_empty() && self.generator.overlay_output.is_none() {\n            errors.push(\n                "generator.overlay_output: required when generator.overlays is non-empty"\n                    .to_string(),\n            );\n        }\n        if self\n            .generator\n            .overlay_output\n            .as_ref()\n            .is_some_and(|output| output == &self.generator.spec_path)\n        {\n            errors.push(\n                "generator.overlay_output: must not overwrite generator.spec_path".to_string(),\n            );\n        }\n        if self.generator.module_name.is_empty() {\n',
)
replace(
    "src/config.rs",
    '    /// Relative `spec_path`, `output_dir`, and `schema_extensions` values are\n    /// resolved against the directory containing `path`, independent of the\n',
    '    /// Relative `spec_path`, `output_dir`, `schema_extensions`, `overlays`, and\n    /// `overlay_output` values are resolved against the directory containing\n    /// `path`, independent of the\n',
)

# Ensure Overlay config survives config round-trips and drives every generate mode.
replace(
    "src/bin/openapi-to-rust.rs",
    'use openapi_to_rust::spec_source::{parse_spec, sanitize_source_provenance};\nuse openapi_to_rust::{CodeGenerator, ConfigFile, GeneratorConfig, SchemaAnalyzer};\n',
    'use openapi_to_rust::overlay::{apply_overlay_files, materialize_document};\nuse openapi_to_rust::spec_source::{parse_spec, sanitize_source_provenance};\nuse openapi_to_rust::{CodeGenerator, ConfigFile, GeneratorConfig, SchemaAnalyzer};\n',
)
replace(
    "src/bin/openapi-to-rust.rs",
    '    let (mut generator_config, load_source, provenance) = match args.source {\n',
    '    let (mut generator_config, load_source, provenance, overlays, overlay_output) =\n        match args.source {\n',
)
replace(
    "src/bin/openapi-to-rust.rs",
    '            (config, source, provenance)\n',
    '            (config, source, provenance, Vec::new(), None)\n',
)
replace(
    "src/bin/openapi-to-rust.rs",
    '            let raw_source = raw_config_spec_source(&config_path)?;\n            let config = ConfigFile::load(&config_path)?.into_generator_config();\n            let load_source = config.spec_path.to_string_lossy().to_string();\n            (config, load_source, sanitize_source_provenance(&raw_source))\n        }\n    };\n',
    '            let raw_source = raw_config_spec_source(&config_path)?;\n            let config_file = ConfigFile::load(&config_path)?;\n            let overlays = config_file.generator.overlays.clone();\n            let overlay_output = config_file.generator.overlay_output.clone();\n            let config = config_file.into_generator_config();\n            let load_source = config.spec_path.to_string_lossy().to_string();\n            (\n                config,\n                load_source,\n                sanitize_source_provenance(&raw_source),\n                overlays,\n                overlay_output,\n            )\n        }\n    };\n',
)
replace(
    "src/bin/openapi-to-rust.rs",
    '    let spec_content = load_spec(&load_source)?;\n    let spec_value = parse_spec(&spec_content, &load_source)?;\n    let warning = openapi_to_rust::spec_source::validate_oas_document(&spec_value)?;\n',
    '    let spec_content = load_spec(&load_source)?;\n    let mut spec_value = parse_spec(&spec_content, &load_source)?;\n    apply_overlay_files(&mut spec_value, &overlays)?;\n    let materialized = overlay_output\n        .as_ref()\n        .map(|_| materialize_document(&spec_value))\n        .transpose()?;\n    let warning = openapi_to_rust::spec_source::validate_oas_document(&spec_value)?;\n',
)
replace(
    "src/bin/openapi-to-rust.rs",
    '    let status = if args.check {\n        check_artifacts(generator.config().output_dir.as_path(), &artifacts)?;\n        "up-to-date"\n    } else if args.dry_run {\n        "dry-run"\n    } else {\n        write_artifacts(generator.config().output_dir.as_path(), &artifacts)?;\n        "generated"\n    };\n',
    '    let status = if args.check {\n        if let (Some(path), Some(expected)) = (&overlay_output, &materialized) {\n            check_materialized(path, expected)?;\n        }\n        check_artifacts(generator.config().output_dir.as_path(), &artifacts)?;\n        "up-to-date"\n    } else if args.dry_run {\n        "dry-run"\n    } else {\n        if let (Some(path), Some(content)) = (&overlay_output, &materialized) {\n            write_materialized(path, content)?;\n        }\n        write_artifacts(generator.config().output_dir.as_path(), &artifacts)?;\n        "generated"\n    };\n',
)
replace(
    "src/bin/openapi-to-rust.rs",
    'fn write_artifacts(\n',
    'fn write_materialized(\n    path: &std::path::Path,\n    content: &str,\n) -> Result<(), Box<dyn std::error::Error>> {\n    if let Some(parent) = path.parent() {\n        std::fs::create_dir_all(parent)?;\n    }\n    std::fs::write(path, content)?;\n    Ok(())\n}\n\nfn check_materialized(\n    path: &std::path::Path,\n    expected: &str,\n) -> Result<(), Box<dyn std::error::Error>> {\n    match std::fs::read_to_string(path) {\n        Ok(actual) if actual == expected => Ok(()),\n        Ok(_) => Err(format!(\n            "materialized OpenAPI is stale: changed: {}\\nRun generation again to update it.",\n            path.display()\n        )\n        .into()),\n        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Err(format!(\n            "materialized OpenAPI is stale: missing: {}\\nRun generation again to update it.",\n            path.display()\n        )\n        .into()),\n        Err(error) => Err(error.into()),\n    }\n}\n\nfn write_artifacts(\n',
)

append(
    "tests/cli_workflow_test.rs",
    r'''
#[test]
fn config_overlays_are_config_relative_deterministic_and_checked() {
    let temp = TempDir::new().unwrap();
    let config_dir = temp.path().join("project/config");
    let elsewhere = temp.path().join("elsewhere");
    std::fs::create_dir_all(&config_dir).unwrap();
    std::fs::create_dir_all(&elsewhere).unwrap();
    std::fs::write(config_dir.join("api.yaml"), SPEC).unwrap();
    std::fs::write(
        config_dir.join("contract.overlay.yaml"),
        r#"overlay: 1.1.0
info:
  title: CLI overlay fixture
  version: '1'
actions:
  - target: $.info.title
    update: Overlaid title
"#,
    )
    .unwrap();
    std::fs::write(
        config_dir.join("openapi-to-rust.toml"),
        r#"[generator]
spec_path = "api.yaml"
output_dir = "generated"
module_name = "api"
overlays = ["contract.overlay.yaml"]
overlay_output = "materialized/openapi.json"

[features]
enable_async_client = false
"#,
    )
    .unwrap();

    let config = config_dir.join("openapi-to-rust.toml");
    let config_arg = config.to_string_lossy().to_string();
    let generated = run(&elsewhere, &["generate", "--config", &config_arg, "--quiet"]);
    assert_success(&generated);

    let materialized = config_dir.join("materialized/openapi.json");
    let first = std::fs::read(&materialized).unwrap();
    let parsed: serde_json::Value = serde_json::from_slice(&first).unwrap();
    assert_eq!(parsed["info"]["title"], "Overlaid title");
    assert!(config_dir.join("generated/types.rs").is_file());

    let repeated = run(&elsewhere, &["generate", "--config", &config_arg, "--quiet"]);
    assert_success(&repeated);
    let second = std::fs::read(&materialized).unwrap();
    assert_eq!(first, second);

    let current = run(
        &elsewhere,
        &["generate", "--config", &config_arg, "--check", "--quiet"],
    );
    assert_success(&current);

    std::fs::write(&materialized, b"{}\n").unwrap();
    let stale = run(
        &elsewhere,
        &["generate", "--config", &config_arg, "--check", "--quiet"],
    );
    assert!(!stale.status.success());
    assert!(String::from_utf8_lossy(&stale.stderr).contains("materialized OpenAPI is stale"));

    let dry_run = run(
        &elsewhere,
        &["generate", "--config", &config_arg, "--dry-run", "--quiet"],
    );
    assert_success(&dry_run);
    assert_eq!(std::fs::read(&materialized).unwrap(), b"{}\n");
}
''',
)
