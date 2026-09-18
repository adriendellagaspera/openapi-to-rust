use crate::client_generator::{
    ClientRequestDiscriminatorPlan, ClientResponseRepresentation, SourceOperationIdentity,
};
use serde::Serialize;
use std::collections::BTreeMap;

/// File name used when generator-owned binding metadata is emitted.
pub const BINDING_MANIFEST_FILE_NAME: &str = "binding-manifest.json";

/// Version of the generator-owned binding metadata contract.
pub const BINDING_MANIFEST_SCHEMA_VERSION: u32 = 1;

/// Deterministic description of the Rust binding surface emitted by this generator.
///
/// Paths are relative to the generated module root because openapi-to-rust does
/// not own the crate path at which consumers mount generated files.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BindingManifest {
    pub schema_version: u32,
    pub generator: BindingManifestGenerator,
    pub structs: BTreeMap<String, Vec<BindingField>>,
    pub enums: BTreeMap<String, Vec<BindingVariant>>,
    pub aliases: BTreeMap<String, String>,
    pub symbol_paths: BTreeMap<String, String>,
    pub operations: Vec<BindingOperation>,
    pub raw_client: RawClientBinding,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BindingManifestGenerator {
    pub name: &'static str,
    pub version: &'static str,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BindingField {
    pub name: String,
    pub wire_name: String,
    #[serde(rename = "type")]
    pub type_name: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BindingVariant {
    pub name: String,
    pub payload: Option<String>,
    pub wire_name: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BindingParameter {
    pub name: String,
    #[serde(rename = "type")]
    pub type_name: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BindingOperationKind {
    CallShape,
    MultipartFilenames,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BindingOperation {
    pub kind: BindingOperationKind,
    pub source_operation: SourceOperationIdentity,
    pub emitted_operation_id: String,
    pub rust_method_name: String,
    pub parameters: Vec<BindingParameter>,
    pub return_type: String,
    pub success_type: String,
    pub representation: ClientResponseRepresentation,
    pub success_statuses: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stream: Option<BindingStreamAbi>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub request_discriminators: Vec<ClientRequestDiscriminatorPlan>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BindingStreamAbi {
    pub alias: String,
    pub item_type: String,
    pub error_type: String,
    pub lifetime: String,
    pub native_type: String,
    pub wasm_type: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RawClientBinding {
    /// Path relative to the generated module root.
    pub type_path: String,
    pub constructor: String,
    pub api_key_builder: String,
    pub base_url_builder: String,
    /// Prelude path relative to the generated module root.
    pub type_preludes: Vec<String>,
}

impl Default for RawClientBinding {
    fn default() -> Self {
        Self {
            type_path: "client::HttpClient".to_string(),
            constructor: "new".to_string(),
            api_key_builder: "with_api_key".to_string(),
            base_url_builder: "with_base_url".to_string(),
            type_preludes: vec!["types::*".to_string()],
        }
    }
}

pub(crate) fn render_rust_type(tokens: proc_macro2::TokenStream) -> crate::Result<String> {
    let ty = syn::parse2::<syn::Type>(tokens).map_err(|error| {
        crate::GeneratorError::CodeGenError(format!(
            "failed to render binding manifest Rust type: {error}"
        ))
    })?;
    let file = syn::parse2::<syn::File>(quote::quote! {
        type __BindingManifestType = #ty;
    })
    .map_err(|error| {
        crate::GeneratorError::CodeGenError(format!(
            "failed to normalize binding manifest Rust type: {error}"
        ))
    })?;
    let rendered = prettyplease::unparse(&file);
    let value = rendered
        .trim()
        .strip_prefix("type __BindingManifestType = ")
        .and_then(|value| value.strip_suffix(';'))
        .ok_or_else(|| {
            crate::GeneratorError::CodeGenError(
                "failed to normalize binding manifest Rust type".to_string(),
            )
        })?;
    Ok(value.to_string())
}

pub(crate) fn stream_abi(
    representation: &ClientResponseRepresentation,
) -> Option<BindingStreamAbi> {
    representation.is_streaming().then(|| BindingStreamAbi {
        alias: "HttpResponseByteStream".to_string(),
        item_type: "bytes::Bytes".to_string(),
        error_type: "reqwest::Error".to_string(),
        lifetime: "'static".to_string(),
        native_type:
            "futures_util::stream::BoxStream<'static, Result<bytes::Bytes, reqwest::Error>>"
                .to_string(),
        wasm_type:
            "futures_util::stream::LocalBoxStream<'static, Result<bytes::Bytes, reqwest::Error>>"
                .to_string(),
    })
}
