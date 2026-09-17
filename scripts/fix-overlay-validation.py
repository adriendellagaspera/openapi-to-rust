from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text()
    if old not in text:
        raise SystemExit(f"expected anchor missing from {path}: {old[:160]!r}")
    target.write_text(text.replace(old, new, 1))


replace(
    "tests/config_test.rs",
    '''        schema_extensions: vec!["overlay.yaml".into()],
        builders: BuildersSection::default(),
''',
    '''        schema_extensions: vec!["extension.yaml".into()],
        overlays: vec!["contract.overlay.yaml".into()],
        overlay_output: Some("materialized/openapi.json".into()),
        builders: BuildersSection::default(),
''',
)
replace(
    "tests/config_test.rs",
    '''    assert_eq!(reparsed.schema_extensions, section.schema_extensions);
    assert_eq!(reparsed.builders, section.builders);
''',
    '''    assert_eq!(reparsed.schema_extensions, section.schema_extensions);
    assert_eq!(reparsed.overlays, section.overlays);
    assert_eq!(reparsed.overlay_output, section.overlay_output);
    assert_eq!(reparsed.builders, section.builders);
''',
)

replace(
    "src/overlay.rs",
    '''    let has_update = action.contains_key("update");
    let has_copy = action.contains_key("copy");
    if has_copy && !action.get("copy").is_some_and(Value::is_string) {
        return Err(invalid(
            source,
            format!("{context}.copy must be an RFC 9535 JSONPath string"),
        ));
    }
    let modifier_count = usize::from(remove) + usize::from(has_update) + usize::from(has_copy);
    if modifier_count != 1 {
        return Err(invalid(
            source,
            format!(
                "{context} must contain exactly one active modifier: update, copy, or remove: true"
            ),
        ));
    }

    let paths = document.query_only_path(target).map_err(|error| {
''',
    '''    let has_update = action.contains_key("update");
    let has_copy = action.contains_key("copy");
    if has_copy && !action.get("copy").is_some_and(Value::is_string) {
        return Err(invalid(
            source,
            format!("{context}.copy must be an RFC 9535 JSONPath string"),
        ));
    }

    let paths = document.query_only_path(target).map_err(|error| {
''',
)
replace(
    "src/overlay.rs",
    '''    ensure_homogeneous_targets(document, &paths, source, &context)?;
    let modifier = if has_update {
        action
            .get("update")
            .cloned()
            .ok_or_else(|| invalid(source, format!("{context}.update is missing")))?
    } else {
        let copy = action
            .get("copy")
            .and_then(Value::as_str)
            .ok_or_else(|| invalid(source, format!("{context}.copy is missing")))?;
        let copied = document.query(copy).map_err(|error| {
            invalid(
                source,
                format!("{context} copy `{copy}` is not valid RFC 9535 JSONPath: {error}"),
            )
        })?;
        if copied.len() != 1 {
            return Err(invalid(
                source,
                format!(
                    "{context} copy `{copy}` must select exactly one node; selected {}",
                    copied.len()
                ),
            ));
        }
        copied[0].clone()
    };

    for path in paths {
''',
    '''    // Overlay 1.1 defines modifier precedence explicitly. `remove: true`
    // suppresses both `update` and `copy`; when both `update` and `copy` are
    // present they suppress each other, so the action is a no-op after target
    // evaluation. A target-only action is likewise valid and has no effect.
    let modifier = match (action.get("update"), action.get("copy")) {
        (Some(_), Some(_)) => return Ok(()),
        (Some(update), None) => update.clone(),
        (None, Some(copy)) => {
            let copy = copy
                .as_str()
                .ok_or_else(|| invalid(source, format!("{context}.copy is missing")))?;
            let copied = document.query(copy).map_err(|error| {
                invalid(
                    source,
                    format!("{context} copy `{copy}` is not valid RFC 9535 JSONPath: {error}"),
                )
            })?;
            if copied.len() != 1 {
                return Err(invalid(
                    source,
                    format!(
                        "{context} copy `{copy}` must select exactly one node; selected {}",
                        copied.len()
                    ),
                ));
            }
            (*copied[0]).clone()
        }
        (None, None) => return Ok(()),
    };

    ensure_homogeneous_targets(document, &paths, source, &context)?;
    for path in paths {
''',
)

replace(
    "src/overlay.rs",
    '''    #[test]
    fn zero_match_succeeds_without_resolving_copy_source() {
''',
    '''    #[test]
    fn remove_takes_precedence_over_update_and_copy() {
        let mut document = json!({"items": [{"name": "keep"}, {"name": "drop"}], "source": {}});
        apply(
            &mut document,
            overlay(json!([{
                "target": "$.items[?@.name == 'drop']",
                "update": {"ignored": true},
                "copy": "$.source",
                "remove": true
            }])),
        )
        .expect("remove takes precedence");
        assert_eq!(document["items"], json!([{"name": "keep"}]));
    }

    #[test]
    fn simultaneous_update_and_copy_is_a_noop() {
        let mut document = json!({"target": {"value": 1}, "source": {"value": 2}});
        let before = document.clone();
        apply(
            &mut document,
            overlay(json!([{
                "target": "$.target",
                "update": {"value": 3},
                "copy": "$.source"
            }])),
        )
        .expect("update and copy suppress each other");
        assert_eq!(document, before);
    }

    #[test]
    fn target_only_action_is_a_noop() {
        let mut document = json!({"target": {"value": 1}});
        let before = document.clone();
        apply(&mut document, overlay(json!([{"target": "$.target"}]))).expect("valid no-op");
        assert_eq!(document, before);
    }

    #[test]
    fn zero_match_succeeds_without_resolving_copy_source() {
''',
)
