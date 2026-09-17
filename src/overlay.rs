//! OpenAPI Overlay 1.1 application and deterministic materialization.
//!
//! Overlay actions are applied sequentially to a JSON representation of the
//! source document. Targets and copy sources use RFC 9535 JSONPath through the
//! `jsonpath-rust` query engine.

use jsonpath_rust::JsonPath;
use jsonpath_rust::query::queryable::Queryable;
use serde_json::{Map, Value};
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use thiserror::Error;

/// Errors produced while loading or applying an OpenAPI Overlay document.
#[derive(Debug, Error)]
pub enum OverlayError {
    /// The overlay file could not be read.
    #[error("failed to read Overlay document '{}': {source}", path.display())]
    Read {
        /// Overlay file path.
        path: PathBuf,
        /// Filesystem error.
        #[source]
        source: std::io::Error,
    },
    /// The overlay file is not valid YAML/JSON.
    #[error("failed to parse Overlay document '{}': {source}", path.display())]
    Parse {
        /// Overlay file path.
        path: PathBuf,
        /// Parser error.
        #[source]
        source: serde_yaml::Error,
    },
    /// The Overlay document or one of its actions is invalid.
    #[error("invalid Overlay document '{}': {message}", path.display())]
    Invalid {
        /// Overlay file path.
        path: PathBuf,
        /// Stable validation/application error.
        message: String,
    },
}

/// Apply Overlay 1.1 files to `document` in the declared file order.
///
/// Each Overlay file applies its actions sequentially to the result of the
/// preceding file. A target that selects zero nodes succeeds without changing
/// the document, as required by Overlay 1.1.
pub fn apply_overlay_files(document: &mut Value, overlays: &[PathBuf]) -> Result<(), OverlayError> {
    for path in overlays {
        apply_overlay_file(document, path)?;
    }
    Ok(())
}

/// Load and apply one Overlay 1.1 YAML or JSON document.
pub fn apply_overlay_file(document: &mut Value, path: &Path) -> Result<(), OverlayError> {
    let source = std::fs::read_to_string(path).map_err(|source| OverlayError::Read {
        path: path.to_path_buf(),
        source,
    })?;
    let overlay: Value = serde_yaml::from_str(&source).map_err(|source| OverlayError::Parse {
        path: path.to_path_buf(),
        source,
    })?;
    apply_overlay(document, &overlay, path)
}

/// Apply an already-parsed Overlay 1.1 document.
///
/// This is primarily useful to embedders that already own parsing/I/O.
pub fn apply_overlay(
    document: &mut Value,
    overlay: &Value,
    source: &Path,
) -> Result<(), OverlayError> {
    let root = require_object(overlay, source, "root")?;
    validate_fields(
        root,
        &["overlay", "info", "extends", "actions"],
        source,
        "root",
    )?;

    let version = require_string(root, "overlay", source, "root")?;
    validate_version(version, source)?;

    let info = root
        .get("info")
        .ok_or_else(|| invalid(source, "root.info is required"))?;
    let info = require_object(info, source, "root.info")?;
    validate_fields(
        info,
        &["title", "version", "description"],
        source,
        "root.info",
    )?;
    require_string(info, "title", source, "root.info")?;
    require_string(info, "version", source, "root.info")?;
    if let Some(description) = info.get("description")
        && !description.is_string()
    {
        return Err(invalid(source, "root.info.description must be a string"));
    }
    if let Some(extends) = root.get("extends")
        && !extends.is_string()
    {
        return Err(invalid(
            source,
            "root.extends must be a string URI reference",
        ));
    }

    let actions = root
        .get("actions")
        .and_then(Value::as_array)
        .ok_or_else(|| invalid(source, "root.actions must be a non-empty array"))?;
    if actions.is_empty() {
        return Err(invalid(source, "root.actions must be a non-empty array"));
    }

    let mut seen = BTreeSet::new();
    for (index, action) in actions.iter().enumerate() {
        let canonical = serde_json::to_string(action).map_err(|error| {
            invalid(
                source,
                format!("action {} cannot be normalized: {error}", index + 1),
            )
        })?;
        if !seen.insert(canonical) {
            return Err(invalid(
                source,
                format!("action {} duplicates an earlier action", index + 1),
            ));
        }
        apply_action(document, action, source, index + 1)?;
    }
    Ok(())
}

/// Serialize an overlaid OpenAPI document deterministically as pretty JSON.
///
/// JSON is valid YAML, and `serde_json::Map` uses deterministic key ordering in
/// this crate, so identical inputs produce identical bytes across executions.
pub fn materialize_document(document: &Value) -> Result<String, serde_json::Error> {
    let mut rendered = serde_json::to_string_pretty(document)?;
    rendered.push('\n');
    Ok(rendered)
}

fn apply_action(
    document: &mut Value,
    action: &Value,
    source: &Path,
    index: usize,
) -> Result<(), OverlayError> {
    let context = format!("action {index}");
    let action = require_object(action, source, &context)?;
    validate_fields(
        action,
        &["target", "description", "update", "copy", "remove"],
        source,
        &context,
    )?;
    let target = require_string(action, "target", source, &context)?;
    if let Some(description) = action.get("description")
        && !description.is_string()
    {
        return Err(invalid(
            source,
            format!("{context}.description must be a string"),
        ));
    }
    let remove = match action.get("remove") {
        Some(Value::Bool(value)) => *value,
        Some(_) => {
            return Err(invalid(
                source,
                format!("{context}.remove must be a boolean"),
            ));
        }
        None => false,
    };
    let has_update = action.contains_key("update");
    let has_copy = action.contains_key("copy");
    if has_copy && !action.get("copy").is_some_and(Value::is_string) {
        return Err(invalid(
            source,
            format!("{context}.copy must be an RFC 9535 JSONPath string"),
        ));
    }

    let paths = document.query_only_path(target).map_err(|error| {
        invalid(
            source,
            format!("{context} target `{target}` is not valid RFC 9535 JSONPath: {error}"),
        )
    })?;
    if paths.is_empty() {
        return Ok(());
    }

    if remove {
        if paths.iter().any(|path| path == "$") {
            return Err(invalid(
                source,
                format!("{context} cannot remove the document root"),
            ));
        }
        document.delete_by_path(target).map_err(|error| {
            invalid(
                source,
                format!("{context} failed to remove target `{target}`: {error}"),
            )
        })?;
        return Ok(());
    }

    // Overlay 1.1 defines modifier precedence explicitly. `remove: true`
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
        let selected = document.reference_mut(path.clone()).ok_or_else(|| {
            invalid(
                source,
                format!("{context} target node `{path}` disappeared during application"),
            )
        })?;
        apply_modifier(
            selected,
            &modifier,
            source,
            &format!("{context} target `{path}`"),
        )?;
    }
    Ok(())
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum NodeKind {
    Object,
    Array,
    Primitive,
}

fn node_kind(value: &Value) -> NodeKind {
    match value {
        Value::Object(_) => NodeKind::Object,
        Value::Array(_) => NodeKind::Array,
        _ => NodeKind::Primitive,
    }
}

fn ensure_homogeneous_targets(
    document: &Value,
    paths: &[String],
    source: &Path,
    context: &str,
) -> Result<(), OverlayError> {
    if paths.len() < 2 {
        return Ok(());
    }
    let first_path = paths
        .first()
        .ok_or_else(|| invalid(source, format!("{context} selected no target nodes")))?;
    let first = document.reference(first_path.clone()).ok_or_else(|| {
        invalid(
            source,
            format!("{context} target node `{first_path}` cannot be resolved"),
        )
    })?;
    let expected = node_kind(first);
    for path in paths.iter().skip(1) {
        let node = document.reference(path.clone()).ok_or_else(|| {
            invalid(
                source,
                format!("{context} target node `{path}` cannot be resolved"),
            )
        })?;
        if node_kind(node) != expected {
            return Err(invalid(
                source,
                format!(
                    "{context} selects mixed node kinds; multi-target update/copy must select only objects, only arrays, or only primitives"
                ),
            ));
        }
    }
    Ok(())
}

fn apply_modifier(
    target: &mut Value,
    modifier: &Value,
    source: &Path,
    context: &str,
) -> Result<(), OverlayError> {
    match target {
        Value::Object(target_object) => {
            let update_object = modifier.as_object().ok_or_else(|| {
                invalid(
                    source,
                    format!("{context} is an object but its update/copy value is not an object"),
                )
            })?;
            merge_objects(target_object, update_object, source, context)
        }
        Value::Array(target_array) => {
            if let Some(update_array) = modifier.as_array() {
                target_array.extend(update_array.iter().cloned());
            } else {
                target_array.push(modifier.clone());
            }
            Ok(())
        }
        _ if is_primitive(target) && is_primitive(modifier) => {
            *target = modifier.clone();
            Ok(())
        }
        _ => Err(invalid(
            source,
            format!("{context} is primitive but its update/copy value is not primitive"),
        )),
    }
}

fn merge_objects(
    target: &mut Map<String, Value>,
    update: &Map<String, Value>,
    source: &Path,
    context: &str,
) -> Result<(), OverlayError> {
    for (key, update_value) in update {
        let Some(target_value) = target.get_mut(key) else {
            target.insert(key.clone(), update_value.clone());
            continue;
        };
        let nested = format!("{context}.{key}");
        match (target_value, update_value) {
            (Value::Object(target_object), Value::Object(update_object)) => {
                merge_objects(target_object, update_object, source, &nested)?;
            }
            (Value::Array(target_array), Value::Array(update_array)) => {
                target_array.extend(update_array.iter().cloned());
            }
            (target_primitive, update_primitive)
                if is_primitive(target_primitive) && is_primitive(update_primitive) =>
            {
                *target_primitive = update_primitive.clone();
            }
            _ => {
                return Err(invalid(
                    source,
                    format!("{nested} has incompatible target and update/copy value types"),
                ));
            }
        }
    }
    Ok(())
}

fn is_primitive(value: &Value) -> bool {
    !matches!(value, Value::Object(_) | Value::Array(_))
}

fn validate_version(version: &str, source: &Path) -> Result<(), OverlayError> {
    let mut parts = version.split('.');
    let major = parts.next();
    let minor = parts.next();
    let patch = parts.next();
    let valid = major == Some("1")
        && minor == Some("1")
        && patch
            .is_some_and(|value| !value.is_empty() && value.chars().all(|c| c.is_ascii_digit()))
        && parts.next().is_none();
    if valid {
        Ok(())
    } else {
        Err(invalid(
            source,
            format!("root.overlay must declare Overlay 1.1.x; found `{version}`"),
        ))
    }
}

fn validate_fields(
    object: &Map<String, Value>,
    allowed: &[&str],
    source: &Path,
    context: &str,
) -> Result<(), OverlayError> {
    for key in object.keys() {
        if !allowed.contains(&key.as_str()) && !key.starts_with("x-") {
            return Err(invalid(
                source,
                format!("{context} contains unknown field `{key}`"),
            ));
        }
    }
    Ok(())
}

fn require_object<'a>(
    value: &'a Value,
    source: &Path,
    context: &str,
) -> Result<&'a Map<String, Value>, OverlayError> {
    value
        .as_object()
        .ok_or_else(|| invalid(source, format!("{context} must be an object")))
}

fn require_string<'a>(
    object: &'a Map<String, Value>,
    key: &str,
    source: &Path,
    context: &str,
) -> Result<&'a str, OverlayError> {
    object
        .get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| invalid(source, format!("{context}.{key} must be a string")))
}

fn invalid(source: &Path, message: impl Into<String>) -> OverlayError {
    OverlayError::Invalid {
        path: source.to_path_buf(),
        message: message.into(),
    }
}

#[cfg(test)]
mod tests {
    use super::{apply_overlay, materialize_document};
    use serde_json::{Value, json};
    use std::path::Path;

    fn apply(document: &mut Value, overlay: Value) -> Result<(), super::OverlayError> {
        apply_overlay(document, &overlay, Path::new("fixture.overlay.yaml"))
    }

    fn overlay(actions: Value) -> Value {
        json!({
            "overlay": "1.1.0",
            "info": {"title": "fixture", "version": "1"},
            "actions": actions,
        })
    }

    #[test]
    fn actions_are_applied_in_declared_order() {
        let mut document = json!({"info": {"title": "before"}});
        apply(
            &mut document,
            overlay(json!([
                {"target": "$.info", "update": {"description": "added"}},
                {"target": "$.info.description", "update": "changed"}
            ])),
        )
        .expect("valid overlay");
        assert_eq!(document["info"]["description"], "changed");
    }

    #[test]
    fn update_merges_objects_concatenates_arrays_and_replaces_primitives() {
        let mut document = json!({
            "node": {"keep": true, "nested": {"value": 1}, "array": [1]}
        });
        apply(
            &mut document,
            overlay(json!([{
                "target": "$.node",
                "update": {"nested": {"value": 2, "new": true}, "array": [2], "extra": "x"}
            }])),
        )
        .expect("valid overlay");
        assert_eq!(
            document["node"],
            json!({
                "keep": true,
                "nested": {"value": 2, "new": true},
                "array": [1, 2],
                "extra": "x"
            })
        );
    }

    #[test]
    fn update_applies_to_multiple_matches() {
        let mut document = json!({"items": [{"n": 1}, {"n": 2}]});
        apply(
            &mut document,
            overlay(json!([{"target": "$.items[*]", "update": {"enabled": true}}])),
        )
        .expect("valid overlay");
        assert_eq!(document["items"][0]["enabled"], true);
        assert_eq!(document["items"][1]["enabled"], true);
    }

    #[test]
    fn remove_deletes_all_selected_array_items_without_index_shift() {
        let mut document = json!({"items": ["keep", "drop", "drop", "keep"]});
        apply(
            &mut document,
            overlay(json!([{"target": "$.items[?@ == 'drop']", "remove": true}])),
        )
        .expect("valid overlay");
        assert_eq!(document["items"], json!(["keep", "keep"]));
    }

    #[test]
    fn copy_selects_one_source_and_merges_into_targets() {
        let mut document = json!({
            "template": {"headers": ["a"], "enabled": true},
            "targets": [{"headers": ["b"]}, {"headers": ["c"]}]
        });
        apply(
            &mut document,
            overlay(json!([{"target": "$.targets[*]", "copy": "$.template"}])),
        )
        .expect("valid overlay");
        assert_eq!(
            document["targets"][0],
            json!({"headers": ["b", "a"], "enabled": true})
        );
        assert_eq!(
            document["targets"][1],
            json!({"headers": ["c", "a"], "enabled": true})
        );
    }

    #[test]
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
        let mut document = json!({"present": true});
        let before = document.clone();
        apply(
            &mut document,
            overlay(json!([{"target": "$.missing", "copy": "$.also_missing"}])),
        )
        .expect("zero-match action succeeds");
        assert_eq!(document, before);
    }

    #[test]
    fn invalid_jsonpath_is_reported_with_action_context() {
        let mut document = json!({"present": true});
        let error = apply(
            &mut document,
            overlay(json!([{"target": "$[", "update": true}])),
        )
        .expect_err("invalid JSONPath");
        let message = error.to_string();
        assert!(message.contains("action 1 target `$[`") && message.contains("RFC 9535 JSONPath"));
    }

    #[test]
    fn empty_target_is_rejected_as_invalid_jsonpath() {
        let mut document = json!({"present": true});
        let error = apply(
            &mut document,
            overlay(json!([{"target": "", "update": true}])),
        )
        .expect_err("empty JSONPath");
        assert!(error.to_string().contains("target ``"));
    }

    #[test]
    fn mixed_multi_target_kinds_are_rejected() {
        let mut document = json!({"object": {}, "primitive": 1});
        let error = apply(
            &mut document,
            overlay(json!([{"target": "$['object','primitive']", "update": {}}])),
        )
        .expect_err("mixed target kinds");
        assert!(error.to_string().contains("mixed node kinds"));
    }

    #[test]
    fn materialization_is_byte_deterministic() {
        let document = json!({"z": 1, "a": {"y": 2, "b": 3}});
        let first = materialize_document(&document).expect("serialize");
        let second = materialize_document(&document).expect("serialize");
        assert_eq!(first.as_bytes(), second.as_bytes());
        assert!(first.ends_with('\n'));
    }
}
