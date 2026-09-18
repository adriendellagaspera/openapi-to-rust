from pathlib import Path

def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"missing anchor in {path}: {old[:100]!r}")
    p.write_text(text.replace(old, new, 1))

def replace_between(path, start, end, new):
    p = Path(path)
    text = p.read_text()
    a = text.find(start)
    if a < 0:
        raise SystemExit(f"missing start in {path}: {start!r}")
    b = text.find(end, a)
    if b < 0:
        raise SystemExit(f"missing end in {path}: {end!r}")
    p.write_text(text[:a] + new + text[b:])

# Public module/export.
replace_once(
    "src/lib.rs",
    "pub mod analysis;\n",
    "pub mod analysis;\npub mod binding_manifest;\n",
)
replace_once(
    "src/lib.rs",
    "pub use analysis::{SchemaAnalysis, SchemaAnalyzer, merge_schema_extensions};\n",
    "pub use analysis::{SchemaAnalysis, SchemaAnalyzer, merge_schema_extensions};\npub use binding_manifest::{\n    BINDING_MANIFEST_SCHEMA, BINDING_MANIFEST_SCHEMA_VERSION, BindingManifest,\n};\n",
)

# Generator helpers used by the manifest must be the same helpers source rendering uses.
for old, new in [
    ("    fn emitted_object_properties<'a>(\n", "    pub(crate) fn emitted_object_properties<'a>(\n"),
    ("    fn variant_field_name(\n", "    pub(crate) fn variant_field_name(\n"),
    ("    fn generate_array_item_type(\n", "    pub(crate) fn generate_array_item_type(\n"),
    ("    fn type_name_to_variant_name(&self, type_name: &str) -> String {\n", "    pub(crate) fn type_name_to_variant_name(&self, type_name: &str) -> String {\n"),
    ("    fn ensure_unique_variant_name_generator(\n", "    pub(crate) fn ensure_unique_variant_name_generator(\n"),
    ("    fn to_rust_type_name(&self, s: &str) -> String {\n", "    pub(crate) fn to_rust_type_name(&self, s: &str) -> String {\n"),
    ("    fn to_rust_enum_variant(&self, s: &str) -> String {\n", "    pub(crate) fn to_rust_enum_variant(&self, s: &str) -> String {\n"),
    ("    fn should_use_untagged_discriminated_union(\n", "    pub(crate) fn should_use_untagged_discriminated_union(\n"),
    ("    fn resolve_operation_scopes(&self, analysis: &SchemaAnalysis) -> Result<OperationScopes> {\n", "    pub(crate) fn resolve_operation_scopes(&self, analysis: &SchemaAnalysis) -> Result<OperationScopes> {\n"),
    ("    fn prune_models_to_scopes(\n", "    pub(crate) fn prune_models_to_scopes(\n"),
]:
    replace_once("src/generator.rs", old, new)

# The scope type crosses the generator/binding-manifest module boundary.
replace_once(
    "src/generator.rs",
    "struct OperationScopes {\n",
    "pub(crate) struct OperationScopes {\n",
)

# Shared enum variant-shape plan.
insert_anchor = "struct TypeGenerationContext<'a> {\n    index: &'a TypeGenerationIndex,\n}\n"
replace_once(
    "src/generator.rs",
    insert_anchor,
    insert_anchor + """
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct EmittedEnumVariantShape {
    pub(crate) rust_name: String,
    pub(crate) payload_type: String,
}

""",
)

# Shared closed/extensible string-enum naming.
anchor = "    fn generate_extensible_enum(\n"
helper = """    pub(crate) fn plan_string_enum_variant_names(
        &self,
        values: &[String],
        ext: Option<&crate::analysis::EnumExtensions>,
        dedupe: bool,
    ) -> Vec<String> {
        let varnames_override = ext
            .filter(|_| self.config.types.x_enum_varnames_enabled())
            .map(|extensions| &extensions.varnames)
            .filter(|varnames| !varnames.is_empty() && varnames.len() == values.len());

        let mut used = std::collections::HashSet::new();
        values
            .iter()
            .enumerate()
            .map(|(index, value)| {
                let base = match varnames_override {
                    Some(varnames) => varnames[index].clone(),
                    None => self.to_rust_enum_variant(value),
                };
                if !dedupe {
                    return base;
                }
                let mut chosen = base.clone();
                let mut suffix = 2;
                while !used.insert(chosen.clone()) {
                    chosen = format!("{base}_{suffix}");
                    suffix += 1;
                }
                chosen
            })
            .collect()
    }

"""
replace_once("src/generator.rs", anchor, helper + anchor)

# Make extensible enum rendering consume the shared name plan.
replace_between(
    "src/generator.rs",
    "        // Q2.6: pre-resolve variant idents from x-enum-varnames when\n",
    "        // For extensible enums, we need a different approach:\n",
    """        // Q2.6 naming is shared with binding metadata.
        let variant_names = self.plan_string_enum_variant_names(known_values, ext, false);
        let descriptions_override: Option<&Vec<String>> = ext
            .filter(|_| self.config.types.x_enum_descriptions_enabled())
            .map(|e| &e.descriptions)
            .filter(|v| !v.is_empty() && v.len() == known_values.len());

        let variant_ident_for = |index: usize| -> proc_macro2::Ident {
            format_ident!("{}", variant_names[index])
        };

""",
)
replace_once(
    "src/generator.rs",
    "            let variant_ident = variant_ident_for(i, value);\n",
    "            let variant_ident = variant_ident_for(i);\n",
)
replace_once(
    "src/generator.rs",
    "            let variant_ident = variant_ident_for(i, value);\n",
    "            let variant_ident = variant_ident_for(i);\n",
)
replace_once(
    "src/generator.rs",
    "            let variant_ident = variant_ident_for(i, value);\n",
    "            let variant_ident = variant_ident_for(i);\n",
)

# Make closed string enum rendering consume the shared name plan.
closed_start = "        // Q2.6: x-enum-varnames overrides the default heuristic when\n"
closed_end = "        let variants =\n"
p = Path("src/generator.rs")
text = p.read_text()
first = text.find(closed_start, text.find("fn generate_string_enum"))
end = text.find(closed_end, first)
if first < 0 or end < 0:
    raise SystemExit("missing closed string enum naming block")
replacement = """        // Q2.6 naming is shared with binding metadata.
        let variant_names = self.plan_string_enum_variant_names(values, ext, true);
        let descriptions_override: Option<&Vec<String>> = ext
            .filter(|_| self.config.types.x_enum_descriptions_enabled())
            .map(|e| &e.descriptions)
            .filter(|v| !v.is_empty() && v.len() == values.len());

        let variant_pairs: Vec<(syn::Ident, &String, bool, Option<String>)> = values
            .iter()
            .enumerate()
            .map(|(i, value)| {
                let variant_ident = format_ident!("{}", variant_names[i]);
                let is_default = if let Some(ref default) = default_value {
                    value == default
                } else {
                    i == 0
                };
                let description = descriptions_override.map(|d| d[i].clone());
                (variant_ident, value, is_default, description)
            })
            .collect();

"""
p.write_text(text[:first] + replacement + text[end:])

# Shared discriminated-union variant payload plan.
disc_anchor = "    fn generate_discriminated_enum(\n"
disc_helper = """    pub(crate) fn plan_discriminated_enum_variants(
        &self,
        schema: &crate::analysis::AnalyzedSchema,
        variants: &[crate::analysis::UnionVariant],
        analysis: &crate::analysis::SchemaAnalysis,
    ) -> Vec<EmittedEnumVariantShape> {
        let enclosing = self.to_rust_type_name(&schema.name);
        variants
            .iter()
            .map(|variant| {
                let variant_type = self.to_rust_type_name(&variant.type_name);
                let payload_type = if variant_type == enclosing
                    || analysis
                        .dependencies
                        .recursive_schemas
                        .contains(&variant.type_name)
                {
                    format!("Box<{variant_type}>")
                } else {
                    variant_type
                };
                EmittedEnumVariantShape {
                    rust_name: variant.rust_name.clone(),
                    payload_type,
                }
            })
            .collect()
    }

"""
replace_once("src/generator.rs", disc_anchor, disc_helper + disc_anchor)

# Replace discriminated variant-shape construction with the shared plan.
replace_between(
    "src/generator.rs",
    "        let enclosing = self.to_rust_type_name(&schema.name);\n",
    "        let enum_variants = variant_shapes.iter().map(|(_, variant_name, payload)| {\n",
    """        let planned_variants =
            self.plan_discriminated_enum_variants(schema, variants, analysis);
        let variant_shapes = variants
            .iter()
            .zip(planned_variants.iter())
            .map(|(variant, planned)| {
                let variant_name = format_ident!("{}", planned.rust_name);
                let payload = parse_rust_type(&planned.payload_type)?;
                Ok((variant, variant_name, payload))
            })
            .collect::<Result<Vec<_>>>()?;
""",
)

# Shared simple-union variant payload plan: extract existing semantics once.
union_anchor = "    fn generate_union_enum(\n"
union_helper = r'''    pub(crate) fn plan_union_enum_variants(
        &self,
        schema: &crate::analysis::AnalyzedSchema,
        variants: &[crate::analysis::SchemaRef],
        analysis: &crate::analysis::SchemaAnalysis,
    ) -> Vec<EmittedEnumVariantShape> {
        let mut used_variant_names = std::collections::HashSet::new();
        variants
            .iter()
            .enumerate()
            .map(|(index, variant)| {
                let base_variant_name = self.type_name_to_variant_name(&variant.target);
                let rust_name = self.ensure_unique_variant_name_generator(
                    base_variant_name,
                    &mut used_variant_names,
                    index,
                );

                let mut payload_type = if matches!(
                    variant.target.as_str(),
                    "bool"
                        | "i8"
                        | "i16"
                        | "i32"
                        | "i64"
                        | "i128"
                        | "u8"
                        | "u16"
                        | "u32"
                        | "u64"
                        | "u128"
                        | "f32"
                        | "f64"
                        | "String"
                ) || variant.target == "serde_json::Value"
                    || variant.target.contains("::")
                    || variant.target.contains('<')
                {
                    variant.target.clone()
                } else if variant.target.starts_with("Vec<") && variant.target.ends_with('>') {
                    variant.target.clone()
                } else {
                    self.to_rust_type_name(&variant.target)
                };

                let target_rust_name = self.to_rust_type_name(&variant.target);
                let enclosing_name = self.to_rust_type_name(&schema.name);
                if target_rust_name == enclosing_name
                    || analysis
                        .dependencies
                        .recursive_schemas
                        .contains(&variant.target)
                {
                    payload_type = format!("Box<{payload_type}>");
                }
                if variant.nullable {
                    payload_type = format!("Option<{payload_type}>");
                }
                EmittedEnumVariantShape {
                    rust_name,
                    payload_type,
                }
            })
            .collect()
    }

'''
replace_once("src/generator.rs", union_anchor, union_helper + union_anchor)

# Replace the simple-union's local naming/type reconstruction with the plan.
replace_between(
    "src/generator.rs",
    "        // Generate meaningful variant names based on type names\n",
    "        let variant_declarations = enum_variants\n",
    """        let planned_variants = self.plan_union_enum_variants(schema, variants, analysis);
        let enum_variants = planned_variants
            .iter()
            .map(|planned| {
                let variant_name = format_ident!("{}", planned.rust_name);
                let variant_type = parse_rust_type(&planned.payload_type)?;
                Ok((variant_name, variant_type))
            })
            .collect::<Result<Vec<_>>>()?;
""",
)

# Client call-shape metadata: make representation types deserializable and attach exact params/return.
replace_once(
    "src/client_generator.rs",
    "#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]\n#[serde(tag = \"kind\", rename_all = \"snake_case\")]\npub enum ClientResponseRepresentation",
    "#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]\n#[serde(tag = \"kind\", rename_all = \"snake_case\")]\npub enum ClientResponseRepresentation",
)
replace_once(
    "src/client_generator.rs",
    "#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, serde::Serialize)]\npub struct SourceOperationIdentity",
    "#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, serde::Serialize, serde::Deserialize)]\npub struct SourceOperationIdentity",
)
replace_once(
    "src/client_generator.rs",
    "#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]\npub struct ClientRequestDiscriminatorPlan",
    "#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]\npub struct ClientRequestDiscriminatorPlan",
)
replace_once(
    "src/client_generator.rs",
    "#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]\npub struct ClientCallShapePlan {\n",
    """#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ClientParameterLocation {
    Path,
    Query,
    Header,
    Cookie,
    Body,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct ClientParameterPlan {
    pub rust_name: String,
    pub wire_name: Option<String>,
    pub location: ClientParameterLocation,
    pub rust_type: String,
    pub required: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct ClientCallShapePlan {
""",
)
replace_once(
    "src/client_generator.rs",
    "    pub success_type: String,\n    pub request_discriminators: Vec<ClientRequestDiscriminatorPlan>,\n",
    "    pub parameters: Vec<ClientParameterPlan>,\n    pub success_type: String,\n    pub return_type: String,\n    pub request_discriminators: Vec<ClientRequestDiscriminatorPlan>,\n",
)

# Parameter planning replaces signature reconstruction.
replace_between(
    "src/client_generator.rs",
    "    fn generate_request_param(&self, op: &OperationInfo) -> TokenStream {\n",
    "    /// Get the Rust type for a parameter\n",
    r'''    fn plan_request_parameters(&self, op: &OperationInfo) -> Vec<ClientParameterPlan> {
        let mut parameters = Vec::new();
        let mut used = std::collections::HashSet::new();
        let mut unique_name = |raw: String| {
            let mut chosen = raw.clone();
            let mut suffix = 2;
            while !used.insert(chosen.clone()) {
                chosen = format!("{raw}_{suffix}");
                suffix += 1;
            }
            chosen
        };

        for (location_name, location) in [
            ("path", ClientParameterLocation::Path),
            ("query", ClientParameterLocation::Query),
            ("header", ClientParameterLocation::Header),
            ("cookie", ClientParameterLocation::Cookie),
        ] {
            for parameter in &op.parameters {
                if parameter.location != location_name {
                    continue;
                }
                let rust_name = unique_name(self.param_ident_str(parameter));
                let base_type = self.get_param_rust_type(parameter);
                let rust_type = if parameter.required || location == ClientParameterLocation::Path {
                    base_type.to_string()
                } else {
                    quote! { Option<#base_type> }.to_string()
                };
                parameters.push(ClientParameterPlan {
                    rust_name,
                    wire_name: Some(parameter.name.clone()),
                    location,
                    rust_type,
                    required: parameter.required,
                });
            }
        }

        if let Some(request_body) = &op.request_body {
            use crate::analysis::RequestBodyContent;
            if !matches!(request_body, RequestBodyContent::SchemaLess { .. }) {
                let (rust_name, body_type) = match request_body {
                    RequestBodyContent::Json { schema_name, .. }
                    | RequestBodyContent::FormUrlEncoded { schema_name, .. }
                    | RequestBodyContent::Multipart { schema_name, .. } => {
                        ("request", self.to_rust_type_name(schema_name))
                    }
                    RequestBodyContent::OctetStream { .. }
                    | RequestBodyContent::Binary { .. }
                    | RequestBodyContent::Unsupported { .. } => ("body", "Vec<u8>".to_string()),
                    RequestBodyContent::TextPlain { .. } => ("body", "String".to_string()),
                    RequestBodyContent::SchemaLess { .. } => unreachable!(),
                };
                let rust_type = if op.request_body_required {
                    body_type
                } else {
                    format!("Option<{body_type}>")
                };
                parameters.push(ClientParameterPlan {
                    rust_name: rust_name.to_string(),
                    wire_name: None,
                    location: ClientParameterLocation::Body,
                    rust_type,
                    required: op.request_body_required,
                });
            }
        }

        parameters
    }

    fn planned_parameter_tokens(parameters: &[ClientParameterPlan]) -> TokenStream {
        let mut rendered = Vec::with_capacity(parameters.len());
        for parameter in parameters {
            let ident = match syn::parse_str::<syn::Ident>(&parameter.rust_name) {
                Ok(ident) => ident,
                Err(error) => {
                    rendered.push(error.to_compile_error());
                    continue;
                }
            };
            let rust_type = match syn::parse_str::<syn::Type>(&parameter.rust_type) {
                Ok(rust_type) => rust_type,
                Err(error) => {
                    rendered.push(error.to_compile_error());
                    continue;
                }
            };
            rendered.push(quote! { #ident: #rust_type });
        }
        quote! { #(#rendered),* }
    }

    fn generate_request_param(&self, op: &OperationInfo) -> TokenStream {
        Self::planned_parameter_tokens(&self.plan_request_parameters(op))
    }

''',
)

# Call-shape constructor owns parameters and complete return type.
replace_between(
    "src/client_generator.rs",
    "    fn build_call_shape_plan(\n",
    "    pub(crate) fn validate_client_request_discriminators(\n",
    r'''    fn build_call_shape_plan(
        &self,
        analysis: &SchemaAnalysis,
        operation: &OperationInfo,
        rust_method_name: String,
        representation: ClientResponseRepresentation,
        success_statuses: Vec<String>,
    ) -> ClientCallShapePlan {
        let request_discriminators =
            self.request_discriminator_plans_for_shape(analysis, operation, &representation);
        let success_type = self.success_type_name(&representation);
        let op_error_type = self.op_error_type_token(operation).to_string();
        let return_type = format!("Result<{success_type}, ApiOpError<{op_error_type}>>");
        ClientCallShapePlan {
            source_operation: Self::source_operation_identity(analysis, operation),
            emitted_operation_id: operation.operation_id.clone(),
            rust_method_name,
            representation,
            success_statuses,
            parameters: self.plan_request_parameters(operation),
            success_type,
            return_type,
            request_discriminators,
        }
    }

''',
)

# Source renderer consumes planned parameters and return type.
replace_once(
    "src/client_generator.rs",
    "        let request_param = self.generate_request_param(op);\n",
    "        let request_param = Self::planned_parameter_tokens(&call_shape.parameters);\n",
)
replace_once(
    "src/client_generator.rs",
    "        let response_type = Self::planned_success_type_tokens(call_shape);\n",
    """        let return_type = match syn::parse_str::<syn::Type>(&call_shape.return_type) {
            Ok(return_type) => quote! { #return_type },
            Err(error) => error.to_compile_error(),
        };
""",
)
replace_once(
    "src/client_generator.rs",
    "            ) -> Result<#response_type, ApiOpError<#op_error_type>> {\n",
    "            ) -> #return_type {\n",
)
# op_error_type is now only needed for error handling generic helper? Remove the local if unused.
replace_once(
    "src/client_generator.rs",
    "        let op_error_type = self.op_error_type_token(op);\n",
    "",
)

# Binding manifest module.
Path("src/binding_manifest.rs").write_text(r'''//! Versioned generator-owned metadata describing the Rust bindings actually emitted.

use crate::analysis::{ObjectAdditionalProperties, SchemaAnalysis, SchemaType};
use crate::client_generator::{
    ClientCallShapePlan, ClientRequestDiscriminatorPlan, ClientResponseRepresentation,
    SourceOperationIdentity,
};
use crate::generator::{CodeGenerator, EmittedEnumVariantShape};
use serde::Serialize;
use std::collections::{BTreeMap, HashSet};

pub const BINDING_MANIFEST_SCHEMA: &str = "openapi-to-rust.binding-manifest";
pub const BINDING_MANIFEST_SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BindingManifest {
    pub schema: &'static str,
    pub schema_version: u32,
    pub generator: BindingManifestGenerator,
    pub structs: BTreeMap<String, BindingManifestStruct>,
    pub enums: BTreeMap<String, BindingManifestEnum>,
    pub aliases: BTreeMap<String, BindingManifestAlias>,
    /// Paths are relative to the generated output module. The caller chooses
    /// where that module is mounted in its crate.
    pub symbol_paths: BTreeMap<String, String>,
    pub operations: Vec<BindingManifestOperation>,
    pub binding: BindingManifestLayout,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BindingManifestGenerator {
    pub name: &'static str,
    pub version: &'static str,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BindingManifestStruct {
    pub source_schema: String,
    pub rust_name: String,
    pub public_path: String,
    pub fields: Vec<BindingManifestField>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BindingManifestField {
    pub rust_name: String,
    pub wire_name: Option<String>,
    pub rust_type: String,
    pub required: bool,
    pub nullable: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BindingManifestEnum {
    pub source_schema: String,
    pub rust_name: String,
    pub public_path: String,
    pub variants: Vec<BindingManifestVariant>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BindingManifestVariant {
    pub rust_name: String,
    pub payload: Option<String>,
    pub wire_name: Option<String>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub discriminator_values: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BindingManifestAlias {
    pub source_schema: String,
    pub rust_name: String,
    pub public_path: String,
    pub target: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BindingManifestOperation {
    pub source_operation: SourceOperationIdentity,
    pub emitted_operation_id: String,
    pub rust_method_name: String,
    pub parameters: Vec<crate::client_generator::ClientParameterPlan>,
    pub return_type: String,
    pub success_type: String,
    pub success_statuses: Vec<String>,
    pub representation: ClientResponseRepresentation,
    pub stream: Option<BindingManifestStreamAbi>,
    pub request_discriminators: Vec<ClientRequestDiscriminatorPlan>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BindingManifestStreamAbi {
    pub type_path: String,
    pub item_type: String,
    pub error_type: String,
    pub lifetime: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BindingManifestLayout {
    pub client: Option<BindingManifestClient>,
    pub type_preludes: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BindingManifestClient {
    pub type_path: String,
    pub constructor: String,
    pub api_key_builder: String,
    pub base_url_builder: String,
    pub response_stream_type_path: Option<String>,
}

impl BindingManifest {
    pub fn to_pretty_json(&self) -> crate::Result<String> {
        let mut rendered = serde_json::to_string_pretty(self).map_err(|error| {
            crate::GeneratorError::CodeGenError(format!(
                "failed to serialize binding manifest: {error}"
            ))
        })?;
        rendered.push('
');
        Ok(rendered)
    }
}

impl CodeGenerator {
    /// Build deterministic metadata from the same scoped/pruned projection
    /// source generation consumes. This method does not mutate caller state.
    pub fn binding_manifest(&self, analysis: &SchemaAnalysis) -> crate::Result<BindingManifest> {
        let mut effective = analysis.clone();
        let scopes = self.resolve_operation_scopes(&effective)?;
        self.prune_models_to_scopes(&mut effective, &scopes);

        let mut structs = BTreeMap::new();
        let mut enums = BTreeMap::new();
        let mut aliases = BTreeMap::new();
        let mut symbol_paths = BTreeMap::new();

        if !self.config().registry_only {
            for schema in effective.schemas.values() {
                let rust_name = self.to_rust_type_name(&schema.name);
                let public_path = format!("types::{rust_name}");
                match &schema.schema_type {
                    SchemaType::Object {
                        properties,
                        required,
                        additional_properties,
                        variant,
                    } => {
                        let emitted = self.emitted_object_properties(
                            &schema.name,
                            properties,
                            required,
                            additional_properties,
                            &effective,
                        );
                        let mut fields = emitted
                            .into_iter()
                            .map(|field| BindingManifestField {
                                rust_name: field.ident.to_string(),
                                wire_name: Some(field.wire_name.to_string()),
                                rust_type: field.field_type.to_string(),
                                required: field.is_required,
                                nullable: field.property.nullable,
                            })
                            .collect::<Vec<_>>();
                        match additional_properties {
                            ObjectAdditionalProperties::Denied
                            | ObjectAdditionalProperties::Closed => {}
                            ObjectAdditionalProperties::Untyped => {
                                fields.push(BindingManifestField {
                                    rust_name: "additional_properties".to_string(),
                                    wire_name: None,
                                    rust_type: "std :: collections :: BTreeMap < String , serde_json :: Value >".to_string(),
                                    required: true,
                                    nullable: false,
                                });
                            }
                            ObjectAdditionalProperties::Typed { value_type } => {
                                let value_type =
                                    self.generate_array_item_type(value_type, &effective).to_string();
                                fields.push(BindingManifestField {
                                    rust_name: "additional_properties".to_string(),
                                    wire_name: None,
                                    rust_type: format!(
                                        "std :: collections :: BTreeMap < String , {value_type} >"
                                    ),
                                    required: true,
                                    nullable: false,
                                });
                            }
                        }
                        if let Some(variant) = variant {
                            fields.push(BindingManifestField {
                                rust_name: self.variant_field_name(properties),
                                wire_name: None,
                                rust_type: self.to_rust_type_name(&variant.target),
                                required: true,
                                nullable: variant.nullable,
                            });
                        }
                        structs.insert(
                            rust_name.clone(),
                            BindingManifestStruct {
                                source_schema: schema.name.clone(),
                                rust_name: rust_name.clone(),
                                public_path: public_path.clone(),
                                fields,
                            },
                        );
                        symbol_paths.insert(rust_name, public_path);
                    }
                    SchemaType::Composition { schemas } => {
                        let fields = schemas
                            .iter()
                            .enumerate()
                            .map(|(index, schema_ref)| BindingManifestField {
                                rust_name: format!("part_{index}"),
                                wire_name: None,
                                rust_type: self.to_rust_type_name(&schema_ref.target),
                                required: true,
                                nullable: schema_ref.nullable,
                            })
                            .collect();
                        structs.insert(
                            rust_name.clone(),
                            BindingManifestStruct {
                                source_schema: schema.name.clone(),
                                rust_name: rust_name.clone(),
                                public_path: public_path.clone(),
                                fields,
                            },
                        );
                        symbol_paths.insert(rust_name, public_path);
                    }
                    SchemaType::StringEnum { values } => {
                        let force_extensible = self
                            .config()
                            .extensible_enum_overrides
                            .get(&schema.name)
                            .or_else(|| {
                                self.config().extensible_enum_overrides.get(&rust_name)
                            })
                            .copied()
                            .unwrap_or(false);
                        let variants = self.binding_string_enum_variants(
                            &effective,
                            &schema.name,
                            values,
                            force_extensible,
                        );
                        enums.insert(
                            rust_name.clone(),
                            BindingManifestEnum {
                                source_schema: schema.name.clone(),
                                rust_name: rust_name.clone(),
                                public_path: public_path.clone(),
                                variants,
                            },
                        );
                        symbol_paths.insert(rust_name, public_path);
                    }
                    SchemaType::ExtensibleEnum { known_values } => {
                        let variants = self.binding_string_enum_variants(
                            &effective,
                            &schema.name,
                            known_values,
                            true,
                        );
                        enums.insert(
                            rust_name.clone(),
                            BindingManifestEnum {
                                source_schema: schema.name.clone(),
                                rust_name: rust_name.clone(),
                                public_path: public_path.clone(),
                                variants,
                            },
                        );
                        symbol_paths.insert(rust_name, public_path);
                    }
                    SchemaType::DiscriminatedUnion { variants, .. } => {
                        let variants = if self
                            .should_use_untagged_discriminated_union(schema, &effective)
                        {
                            let refs = variants
                                .iter()
                                .map(|variant| crate::analysis::SchemaRef {
                                    target: variant.type_name.clone(),
                                    nullable: false,
                                })
                                .collect::<Vec<_>>();
                            self.plan_union_enum_variants(schema, &refs, &effective)
                                .into_iter()
                                .map(Self::binding_variant_from_shape)
                                .collect()
                        } else {
                            self.plan_discriminated_enum_variants(schema, variants, &effective)
                                .into_iter()
                                .zip(variants)
                                .map(|(shape, variant)| BindingManifestVariant {
                                    rust_name: shape.rust_name,
                                    payload: Some(shape.payload_type),
                                    wire_name: None,
                                    discriminator_values: variant.discriminator_values.clone(),
                                })
                                .collect()
                        };
                        enums.insert(
                            rust_name.clone(),
                            BindingManifestEnum {
                                source_schema: schema.name.clone(),
                                rust_name: rust_name.clone(),
                                public_path: public_path.clone(),
                                variants,
                            },
                        );
                        symbol_paths.insert(rust_name, public_path);
                    }
                    SchemaType::Union { variants, .. } => {
                        let variants = self
                            .plan_union_enum_variants(schema, variants, &effective)
                            .into_iter()
                            .map(Self::binding_variant_from_shape)
                            .collect();
                        enums.insert(
                            rust_name.clone(),
                            BindingManifestEnum {
                                source_schema: schema.name.clone(),
                                rust_name: rust_name.clone(),
                                public_path: public_path.clone(),
                                variants,
                            },
                        );
                        symbol_paths.insert(rust_name, public_path);
                    }
                    SchemaType::Reference { target } if schema.name == *target => {}
                    SchemaType::Reference { target } => {
                        aliases.insert(
                            rust_name.clone(),
                            BindingManifestAlias {
                                source_schema: schema.name.clone(),
                                rust_name: rust_name.clone(),
                                public_path: public_path.clone(),
                                target: self.to_rust_type_name(target),
                            },
                        );
                        symbol_paths.insert(rust_name, public_path);
                    }
                    SchemaType::Primitive { .. }
                    | SchemaType::Untyped { .. }
                    | SchemaType::Tuple { .. }
                    | SchemaType::Array { .. }
                    | SchemaType::Nullable { .. } => {
                        let target = self
                            .generate_array_item_type(&schema.schema_type, &effective)
                            .to_string();
                        aliases.insert(
                            rust_name.clone(),
                            BindingManifestAlias {
                                source_schema: schema.name.clone(),
                                rust_name: rust_name.clone(),
                                public_path: public_path.clone(),
                                target,
                            },
                        );
                        symbol_paths.insert(rust_name, public_path);
                    }
                }
            }
        }

        let call_shapes = if self.config().enable_async_client && !self.config().registry_only {
            self.try_plan_client_call_shapes(&effective)?
        } else {
            Vec::new()
        };
        let has_stream = call_shapes
            .iter()
            .any(|shape| shape.representation.is_streaming());
        let operations = call_shapes
            .into_iter()
            .map(|shape| BindingManifestOperation {
                stream: shape
                    .representation
                    .is_streaming()
                    .then(|| BindingManifestStreamAbi {
                        type_path: "client::HttpResponseByteStream".to_string(),
                        item_type: "bytes::Bytes".to_string(),
                        error_type: "reqwest::Error".to_string(),
                        lifetime: "'static".to_string(),
                    }),
                source_operation: shape.source_operation,
                emitted_operation_id: shape.emitted_operation_id,
                rust_method_name: shape.rust_method_name,
                parameters: shape.parameters,
                return_type: shape.return_type,
                success_type: shape.success_type,
                success_statuses: shape.success_statuses,
                representation: shape.representation,
                request_discriminators: shape.request_discriminators,
            })
            .collect();

        Ok(BindingManifest {
            schema: BINDING_MANIFEST_SCHEMA,
            schema_version: BINDING_MANIFEST_SCHEMA_VERSION,
            generator: BindingManifestGenerator {
                name: "openapi-to-rust",
                version: crate::VERSION,
            },
            structs,
            enums,
            aliases,
            symbol_paths,
            operations,
            binding: BindingManifestLayout {
                client: (self.config().enable_async_client && !self.config().registry_only).then(
                    || BindingManifestClient {
                        type_path: "client::HttpClient".to_string(),
                        constructor: "new".to_string(),
                        api_key_builder: "with_api_key".to_string(),
                        base_url_builder: "with_base_url".to_string(),
                        response_stream_type_path: has_stream
                            .then(|| "client::HttpResponseByteStream".to_string()),
                    },
                ),
                type_preludes: (!self.config().registry_only)
                    .then(|| vec!["types::*".to_string()])
                    .unwrap_or_default(),
            },
        })
    }

    fn binding_variant_from_shape(shape: EmittedEnumVariantShape) -> BindingManifestVariant {
        BindingManifestVariant {
            rust_name: shape.rust_name,
            payload: Some(shape.payload_type),
            wire_name: None,
            discriminator_values: Vec::new(),
        }
    }

    fn binding_string_enum_variants(
        &self,
        analysis: &SchemaAnalysis,
        schema_name: &str,
        values: &[String],
        extensible: bool,
    ) -> Vec<BindingManifestVariant> {
        let ext = analysis.enum_extensions.get(schema_name);
        let names = self.plan_string_enum_variant_names(values, ext, !extensible);
        let mut variants = names
            .into_iter()
            .zip(values)
            .map(|(rust_name, wire_name)| BindingManifestVariant {
                rust_name,
                payload: None,
                wire_name: Some(wire_name.clone()),
                discriminator_values: Vec::new(),
            })
            .collect::<Vec<_>>();
        if extensible {
            variants.push(BindingManifestVariant {
                rust_name: "Custom".to_string(),
                payload: Some("String".to_string()),
                wire_name: None,
                discriminator_values: Vec::new(),
            });
        }
        variants
    }
}
''')

# Fix visibility of representation helper used by the manifest.
replace_once(
    "src/client_generator.rs",
    "    fn is_streaming(&self) -> bool {\n",
    "    pub(crate) fn is_streaming(&self) -> bool {\n",
)

# Generic library-level manifest fixture.
Path("tests/binding_manifest_test.rs").write_text(r'''use openapi_to_rust::binding_manifest::{
    BINDING_MANIFEST_SCHEMA, BINDING_MANIFEST_SCHEMA_VERSION,
};
use openapi_to_rust::client_generator::ClientResponseRepresentation;
use openapi_to_rust::config::{
    ClientSection, RequestDiscriminatorRule, RequestDiscriminatorTransport,
    RequestDiscriminatorValue,
};
use openapi_to_rust::{CodeGenerator, GeneratorConfig, SchemaAnalyzer};
use serde_json::json;
use std::path::PathBuf;

fn fixture() -> serde_json::Value {
    json!({
        "openapi": "3.1.0",
        "info": {"title": "Binding manifest", "version": "1.0.0"},
        "paths": {
            "/items/{item-id}": {
                "post": {
                    "operationId": "render-item",
                    "parameters": [
                        {
                            "name": "item-id",
                            "in": "path",
                            "required": true,
                            "schema": {"type": "string"}
                        },
                        {
                            "name": "trace-id",
                            "in": "query",
                            "required": false,
                            "schema": {"type": "string"}
                        }
                    ],
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
                            "description": "multiple representations",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/RenderResult"}
                                },
                                "text/event-stream": {"schema": {"type": "string"}},
                                "audio/wav": {"schema": {"type": "string", "format": "binary"}}
                            }
                        }
                    }
                }
            },
            "/other": {
                "get": {
                    "operationId": "render_item",
                    "responses": {
                        "200": {
                            "description": "ok",
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
        "components": {"schemas": {
            "Identifier": {"type": "string"},
            "IdentifierList": {
                "type": "array",
                "items": {"$ref": "#/components/schemas/Identifier"}
            },
            "RenderMode": {
                "type": "string",
                "enum": ["buffered-result", "live-events"],
                "x-enum-varnames": ["BufferedResult", "LiveEvents"]
            },
            "RenderRequest": {
                "type": "object",
                "required": ["mode"],
                "properties": {
                    "mode": {"$ref": "#/components/schemas/RenderMode"},
                    "display-name": {"type": "string"}
                }
            },
            "RenderResult": {
                "type": "object",
                "required": ["id"],
                "properties": {"id": {"$ref": "#/components/schemas/Identifier"}}
            }
        }}
    })
}

fn generator() -> CodeGenerator {
    CodeGenerator::new(GeneratorConfig {
        spec_path: PathBuf::from("fixture.json"),
        output_dir: PathBuf::from("target/binding-manifest"),
        module_name: "fixture".to_string(),
        enable_async_client: true,
        client: Some(ClientSection {
            operations: Vec::new(),
            prune_models: false,
            request_discriminators: vec![RequestDiscriminatorRule {
                operation: "POST /items/{item-id}".to_string(),
                transport: RequestDiscriminatorTransport::EventStream,
                media_type: "text/event-stream".to_string(),
                field: "mode".to_string(),
                value: RequestDiscriminatorValue::String("live-events".to_string()),
            }],
        }),
        ..Default::default()
    })
}

#[test]
fn manifest_is_versioned_deterministic_and_generator_owned()
-> Result<(), Box<dyn std::error::Error>> {
    let mut analyzer = SchemaAnalyzer::new(fixture())?;
    let analysis = analyzer.analyze()?;
    let generator = generator();

    let manifest = generator.binding_manifest(&analysis)?;
    assert_eq!(manifest.schema, BINDING_MANIFEST_SCHEMA);
    assert_eq!(manifest.schema_version, BINDING_MANIFEST_SCHEMA_VERSION);
    assert_eq!(manifest.generator.name, "openapi-to-rust");
    assert_eq!(manifest.to_pretty_json()?, generator.binding_manifest(&analysis)?.to_pretty_json()?);

    let request = &manifest.structs["RenderRequest"];
    let display_name = request
        .fields
        .iter()
        .find(|field| field.wire_name.as_deref() == Some("display-name"))
        .expect("renamed field");
    assert_eq!(display_name.rust_name, "display_name");
    assert!(display_name.rust_type.contains("Option"));
    assert!(!display_name.required);

    let mode = &manifest.enums["RenderMode"];
    assert_eq!(mode.variants[0].rust_name, "BufferedResult");
    assert_eq!(mode.variants[0].wire_name.as_deref(), Some("buffered-result"));

    assert_eq!(manifest.aliases["Identifier"].target, "String");
    assert!(manifest.aliases["IdentifierList"].target.contains("Vec"));
    assert_eq!(manifest.symbol_paths["Identifier"], "types::Identifier");

    let render_shapes = manifest
        .operations
        .iter()
        .filter(|operation| operation.source_operation.operation_id == "render-item")
        .collect::<Vec<_>>();
    assert!(render_shapes.len() >= 4);
    assert!(render_shapes.iter().all(|operation| {
        operation.source_operation.method.eq_ignore_ascii_case("post")
            && operation.source_operation.path == "/items/{item-id}"
    }));
    let json = render_shapes
        .iter()
        .find(|operation| matches!(operation.representation, ClientResponseRepresentation::Json { .. }))
        .expect("json shape");
    assert_eq!(
        json.parameters.iter().map(|parameter| parameter.rust_name.as_str()).collect::<Vec<_>>(),
        vec!["item_id", "trace_id", "request"]
    );
    assert!(json.return_type.contains(&json.success_type));
    assert!(json.request_discriminators.is_empty());

    let sse = render_shapes
        .iter()
        .find(|operation| matches!(operation.representation, ClientResponseRepresentation::EventStream { .. }))
        .expect("sse shape");
    assert_eq!(sse.request_discriminators.len(), 1);
    let stream = sse.stream.as_ref().expect("stream ABI");
    assert_eq!(stream.item_type, "bytes::Bytes");
    assert_eq!(stream.error_type, "reqwest::Error");
    assert_eq!(stream.lifetime, "'static");

    assert!(render_shapes.iter().any(|operation| {
        matches!(
            operation.representation,
            ClientResponseRepresentation::BinaryBuffered { .. }
        )
    }));
    assert!(render_shapes.iter().any(|operation| {
        matches!(
            operation.representation,
            ClientResponseRepresentation::BinaryStream { .. }
        )
    }));

    let other = manifest
        .operations
        .iter()
        .find(|operation| operation.source_operation.path == "/other")
        .expect("colliding operation retained");
    assert_eq!(other.source_operation.operation_id, "render_item");
    assert_ne!(other.rust_method_name, json.rust_method_name);
    Ok(())
}

#[test]
fn manifest_applies_client_scope_and_model_pruning_without_mutating_input()
-> Result<(), Box<dyn std::error::Error>> {
    let mut analyzer = SchemaAnalyzer::new(fixture())?;
    let analysis = analyzer.analyze()?;
    let original_schema_count = analysis.schemas.len();

    let mut config = generator().config().clone();
    config.client = Some(ClientSection {
        operations: vec!["GET /other".to_string()],
        prune_models: true,
        request_discriminators: Vec::new(),
    });
    let manifest = CodeGenerator::new(config).binding_manifest(&analysis)?;

    assert_eq!(analysis.schemas.len(), original_schema_count);
    assert!(manifest
        .operations
        .iter()
        .all(|operation| operation.source_operation.path == "/other"));
    assert!(!manifest.structs.contains_key("RenderRequest"));
    assert!(manifest.structs.contains_key("RenderResult"));
    Ok(())
}
''')
\n# trigger one-shot workflow\n