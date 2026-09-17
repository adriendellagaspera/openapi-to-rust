from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"missing replacement anchor in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1))


# --- Config contract -------------------------------------------------------
replace_once(
    "src/config.rs",
    '''pub struct ClientSection {
    /// Selectors picking client methods: `operationId`, `METHOD /path`, or
    /// `tag:<name>`. Empty means all operations.
    #[serde(default)]
    pub operations: Vec<String>,
    /// Restrict `types.rs` to models reachable from the selected client
    /// operations plus any selected server operations.
    #[serde(default)]
    pub prune_models: bool,
}

impl ClientSection {''',
    '''pub struct ClientSection {
    /// Selectors picking client methods: `operationId`, `METHOD /path`, or
    /// `tag:<name>`. Empty means all operations.
    #[serde(default)]
    pub operations: Vec<String>,
    /// Restrict `types.rs` to models reachable from the selected client
    /// operations plus any selected server operations.
    #[serde(default)]
    pub prune_models: bool,
    /// Representation-specific request fields that the raw client owns.
    ///
    /// Rules bind by source operation selector + response representation and
    /// OpenAPI wire field name. Generated Rust method names are intentionally
    /// absent from this contract.
    #[serde(default)]
    pub request_discriminators: Vec<RequestDiscriminatorRule>,
}

/// Transport dimension used to select one response call shape for a request
/// discriminator. Media type is configured separately so alternate buffered
/// binary/text/JSON representations remain distinguishable.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RequestDiscriminatorTransport {
    Buffered,
    EventStream,
    BinaryStream,
}

/// Scalar request discriminator value. Floats are deliberately excluded from
/// v1: request representation switches are expected to be discrete, and this
/// keeps the generator-owned metadata fully `Eq` and deterministic.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(untagged)]
pub enum RequestDiscriminatorValue {
    Bool(bool),
    Integer(i64),
    String(String),
}

/// One representation-specific request assignment owned by the raw client.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RequestDiscriminatorRule {
    /// Exactly one source operation selector. Tags are accepted only when they
    /// resolve to one operation.
    pub operation: String,
    pub transport: RequestDiscriminatorTransport,
    pub media_type: String,
    /// OpenAPI request-model wire field name, not a Rust identifier.
    pub field: String,
    pub value: RequestDiscriminatorValue,
}

impl ClientSection {''',
)

replace_once(
    "src/config.rs",
    '''        if let Some(client) = &self.client {
            for (index, selector) in client.operations.iter().enumerate() {
                if let Err(error) = crate::server::Selector::parse(selector) {
                    errors.push(format!("client.operations[{index}]: {error}"));
                }
            }
        }
''',
    '''        if let Some(client) = &self.client {
            for (index, selector) in client.operations.iter().enumerate() {
                if let Err(error) = crate::server::Selector::parse(selector) {
                    errors.push(format!("client.operations[{index}]: {error}"));
                }
            }
            for (index, rule) in client.request_discriminators.iter().enumerate() {
                let prefix = format!("client.request_discriminators[{index}]");
                if let Err(error) = crate::server::Selector::parse(&rule.operation) {
                    errors.push(format!("{prefix}.operation: {error}"));
                }
                if rule.media_type.trim().is_empty() {
                    errors.push(format!("{prefix}.media_type: must not be empty"));
                }
                if rule.field.trim().is_empty() {
                    errors.push(format!("{prefix}.field: must not be empty"));
                }
            }
        }
''',
)

# Existing Rust struct literals must name the additive field. Keep public API
# source-compatible through explicit empty values in repository-owned callers.
for filename in [
    "tests/selective_client_test.rs",
    "tests/request_model_ergonomics_test.rs",
    "tests/operation_builder_test.rs",
    "tests/server_raw_body_roundtrip_test.rs",
]:
    p = Path(filename)
    text = p.read_text()
    needle = "ClientSection {"
    cursor = 0
    insertions = []
    while True:
        start = text.find(needle, cursor)
        if start < 0:
            break
        brace = text.find("{", start)
        depth = 0
        end = None
        for i in range(brace, len(text)):
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end is None:
            raise SystemExit(f"unbalanced ClientSection literal in {filename}")
        block = text[start:end]
        if "request_discriminators:" not in block:
            line_start = text.rfind("\n", 0, end) + 1
            close_indent = text[line_start:end]
            field_indent = close_indent + "    "
            insertions.append((end, f"{field_indent}request_discriminators: Vec::new(),\n{close_indent}"))
        cursor = end + 1
    for at, addition in reversed(insertions):
        text = text[:at] + addition + text[at:]
    p.write_text(text)

# --- Shared client/request planning ---------------------------------------
replace_once(
    "src/client_generator.rs",
    '''use crate::generator::CodeGenerator;
''',
    '''use crate::config::{
    RequestDiscriminatorRule, RequestDiscriminatorTransport, RequestDiscriminatorValue,
};
use crate::generator::CodeGenerator;
''',
)

replace_once(
    "src/client_generator.rs",
    '''struct BodyFieldPlan {
    wire_name: String,
    preferred_method_name: String,
    value_ident: syn::Ident,
    value_type: TokenStream,
    access_path: Vec<syn::Ident>,
    tri_state: bool,
}
''',
    '''struct BodyFieldPlan {
    wire_name: String,
    preferred_method_name: String,
    value_ident: syn::Ident,
    value_type: TokenStream,
    access_path: Vec<syn::Ident>,
    is_required: bool,
    nullable: bool,
    tri_state: bool,
    schema_type: crate::analysis::SchemaType,
}
''',
)

replace_once(
    "src/client_generator.rs",
    '''#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct ClientCallShapePlan {
    pub source_operation: SourceOperationIdentity,
    pub emitted_operation_id: String,
    pub rust_method_name: String,
    pub representation: ClientResponseRepresentation,
    pub success_statuses: Vec<String>,
    pub success_type: String,
}
''',
    '''/// One validated request discriminator attached to the exact response
/// representation it selects. The access path and Rust value type come from
/// the same emitted request-model projection used by source rendering.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct ClientRequestDiscriminatorPlan {
    pub wire_name: String,
    pub rust_access_path: Vec<String>,
    pub rust_value_type: String,
    pub value: RequestDiscriminatorValue,
    pub field_required: bool,
    pub field_nullable: bool,
    pub field_tri_state: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct ClientCallShapePlan {
    pub source_operation: SourceOperationIdentity,
    pub emitted_operation_id: String,
    pub rust_method_name: String,
    pub representation: ClientResponseRepresentation,
    pub success_statuses: Vec<String>,
    pub success_type: String,
    pub request_discriminators: Vec<ClientRequestDiscriminatorPlan>,
}
''',
)

replace_once(
    "src/client_generator.rs",
    '''struct BodyModelPlan {
    body_ident: syn::Ident,
    body_type: TokenStream,
    required_construction: RequiredBodyConstruction,
    optional_fields: Vec<BodyFieldPlan>,
}
''',
    '''struct BodyModelPlan {
    body_ident: syn::Ident,
    body_type: TokenStream,
    required_construction: RequiredBodyConstruction,
    all_fields: Vec<BodyFieldPlan>,
    optional_fields: Vec<BodyFieldPlan>,
}
''',
)

replace_once(
    "src/client_generator.rs",
    '''    pub fn generate_operation_methods(&self, analysis: &SchemaAnalysis) -> TokenStream {
        let operations: Vec<&OperationInfo> = analysis.operations.values().collect();
        self.generate_operation_methods_for(analysis, &operations)
    }
''',
    '''    pub fn generate_operation_methods(&self, analysis: &SchemaAnalysis) -> TokenStream {
        let operations: Vec<&OperationInfo> = analysis.operations.values().collect();
        if let Err(error) = self.validate_client_request_discriminators(analysis, &operations) {
            let message = error.to_string();
            return quote! { compile_error!(#message); };
        }
        self.generate_operation_methods_for(analysis, &operations)
    }
''',
)

replace_once(
    "src/client_generator.rs",
    '''    pub fn plan_client_call_shapes(&self, analysis: &SchemaAnalysis) -> Vec<ClientCallShapePlan> {
        let operations: Vec<&OperationInfo> = analysis.operations.values().collect();
        self.plan_client_operation_methods(analysis, &operations)
            .into_iter()
            .flat_map(|plan| plan.call_shapes)
            .collect()
    }
''',
    '''    pub fn plan_client_call_shapes(&self, analysis: &SchemaAnalysis) -> Vec<ClientCallShapePlan> {
        let operations: Vec<&OperationInfo> = analysis.operations.values().collect();
        self.plan_client_operation_methods(analysis, &operations)
            .into_iter()
            .flat_map(|plan| plan.call_shapes)
            .collect()
    }

    /// Fail-closed call-shape planning for consumers that need generator-owned
    /// request discriminator metadata as well as response transport identity.
    pub fn try_plan_client_call_shapes(
        &self,
        analysis: &SchemaAnalysis,
    ) -> crate::Result<Vec<ClientCallShapePlan>> {
        let operations: Vec<&OperationInfo> = analysis.operations.values().collect();
        self.validate_client_request_discriminators(analysis, &operations)?;
        Ok(self.plan_client_operation_methods(analysis, &operations)
            .into_iter()
            .flat_map(|plan| plan.call_shapes)
            .collect())
    }
''',
)

replace_once(
    "src/client_generator.rs",
    '''        ClientCallShapePlan {
            source_operation: Self::source_operation_identity(analysis, operation),
            emitted_operation_id: operation.operation_id.clone(),
            success_type: self.success_type_name(&representation),
            rust_method_name,
            representation,
            success_statuses,
        }
    }
''',
    '''        let request_discriminators =
            self.request_discriminator_plans_for_shape(analysis, operation, &representation);
        ClientCallShapePlan {
            source_operation: Self::source_operation_identity(analysis, operation),
            emitted_operation_id: operation.operation_id.clone(),
            success_type: self.success_type_name(&representation),
            rust_method_name,
            representation,
            success_statuses,
            request_discriminators,
        }
    }

    pub(crate) fn validate_client_request_discriminators(
        &self,
        analysis: &SchemaAnalysis,
        operations: &[&OperationInfo],
    ) -> crate::Result<()> {
        let Some(client) = self.config().client.as_ref() else {
            return Ok(());
        };
        if client.request_discriminators.is_empty() {
            return Ok(());
        }

        let selected_ids: std::collections::HashSet<&str> = operations
            .iter()
            .map(|operation| operation.operation_id.as_str())
            .collect();
        let mut seen = std::collections::BTreeSet::new();

        for (index, rule) in client.request_discriminators.iter().enumerate() {
            let prefix = format!("client.request_discriminators[{index}]");
            let resolution = crate::server::resolve_operation_selectors(
                std::slice::from_ref(&rule.operation),
                analysis,
            )
            .map_err(|error| {
                crate::GeneratorError::ValidationError(format!(
                    "{prefix}.operation `{}` did not resolve: {error}",
                    rule.operation
                ))
            })?;
            if resolution.operations.len() != 1 {
                return Err(crate::GeneratorError::ValidationError(format!(
                    "{prefix}.operation `{}` resolved to {} operations; request discriminators require exactly one source operation",
                    rule.operation,
                    resolution.operations.len(),
                )));
            }
            let target = &resolution.operations[0];
            if !selected_ids.contains(target.operation_id.as_str()) {
                return Err(crate::GeneratorError::ValidationError(format!(
                    "{prefix}.operation `{}` resolves to `{}`, which is not emitted by the configured client scope",
                    rule.operation, target.operation_id,
                )));
            }
            let operation = analysis.operations.get(&target.operation_id).ok_or_else(|| {
                crate::GeneratorError::ValidationError(format!(
                    "{prefix}.operation resolved to missing analyzed operation `{}`",
                    target.operation_id
                ))
            })?;

            let planned = self.plan_client_operation_methods(analysis, &[operation]);
            let matches: Vec<_> = planned
                .first()
                .into_iter()
                .flat_map(|plan| &plan.call_shapes)
                .filter(|shape| Self::request_discriminator_representation_matches(
                    &shape.representation,
                    rule.transport,
                    &rule.media_type,
                ))
                .collect();
            if matches.len() != 1 {
                return Err(crate::GeneratorError::ValidationError(format!(
                    "{prefix}: representation {:?} `{}` resolved to {} call shapes for `{}`; expected exactly one",
                    rule.transport,
                    rule.media_type,
                    matches.len(),
                    target.operation_id,
                )));
            }

            if !operation.request_body_required {
                return Err(crate::GeneratorError::ValidationError(format!(
                    "{prefix}: operation `{}` has an optional request body; v1 request discriminators require a required typed request model",
                    target.operation_id,
                )));
            }
            let body_plan = self.body_model_plan(operation, analysis).ok_or_else(|| {
                crate::GeneratorError::ValidationError(format!(
                    "{prefix}: operation `{}` does not have a typed request model",
                    target.operation_id,
                ))
            })?;
            if body_plan.all_fields.is_empty() {
                return Err(crate::GeneratorError::ValidationError(format!(
                    "{prefix}: operation `{}` request body is not an assignable generated request model",
                    target.operation_id,
                )));
            }
            let fields: Vec<_> = body_plan
                .all_fields
                .iter()
                .filter(|field| field.wire_name == rule.field)
                .collect();
            if fields.len() != 1 {
                return Err(crate::GeneratorError::ValidationError(format!(
                    "{prefix}.field `{}` resolved to {} emitted request fields for `{}`; expected exactly one wire-name match",
                    rule.field,
                    fields.len(),
                    target.operation_id,
                )));
            }
            let field = fields[0];
            if !Self::request_discriminator_value_is_compatible(
                &rule.value,
                &field.schema_type,
                analysis,
                &mut std::collections::HashSet::new(),
            ) {
                return Err(crate::GeneratorError::ValidationError(format!(
                    "{prefix}.value is incompatible with request field `{}` (Rust value type `{}`)",
                    rule.field,
                    field.value_type,
                )));
            }

            let duplicate_key = (
                target.operation_id.clone(),
                rule.transport,
                rule.media_type.to_ascii_lowercase(),
                rule.field.clone(),
            );
            if !seen.insert(duplicate_key) {
                return Err(crate::GeneratorError::ValidationError(format!(
                    "{prefix}: duplicate request discriminator for operation `{}`, representation {:?} `{}`, field `{}`",
                    target.operation_id, rule.transport, rule.media_type, rule.field,
                )));
            }
        }
        Ok(())
    }

    fn request_discriminator_plans_for_shape(
        &self,
        analysis: &SchemaAnalysis,
        operation: &OperationInfo,
        representation: &ClientResponseRepresentation,
    ) -> Vec<ClientRequestDiscriminatorPlan> {
        let Some(client) = self.config().client.as_ref() else {
            return Vec::new();
        };
        if !operation.request_body_required {
            return Vec::new();
        }
        let Some(body_plan) = self.body_model_plan(operation, analysis) else {
            return Vec::new();
        };

        let mut planned = Vec::new();
        for rule in &client.request_discriminators {
            if !Self::request_discriminator_representation_matches(
                representation,
                rule.transport,
                &rule.media_type,
            ) {
                continue;
            }
            let Ok(resolution) = crate::server::resolve_operation_selectors(
                std::slice::from_ref(&rule.operation),
                analysis,
            ) else {
                continue;
            };
            if resolution.operations.len() != 1
                || resolution.operations[0].operation_id != operation.operation_id
            {
                continue;
            }
            let mut fields = body_plan
                .all_fields
                .iter()
                .filter(|field| field.wire_name == rule.field);
            let Some(field) = fields.next() else {
                continue;
            };
            if fields.next().is_some()
                || !Self::request_discriminator_value_is_compatible(
                    &rule.value,
                    &field.schema_type,
                    analysis,
                    &mut std::collections::HashSet::new(),
                )
            {
                continue;
            }
            planned.push(ClientRequestDiscriminatorPlan {
                wire_name: field.wire_name.clone(),
                rust_access_path: field.access_path.iter().map(ToString::to_string).collect(),
                rust_value_type: field.value_type.to_string(),
                value: rule.value.clone(),
                field_required: field.is_required,
                field_nullable: field.nullable,
                field_tri_state: field.tri_state,
            });
        }
        planned
    }

    fn request_discriminator_representation_matches(
        representation: &ClientResponseRepresentation,
        transport: RequestDiscriminatorTransport,
        media_type: &str,
    ) -> bool {
        let (candidate_transport, candidate_media_type) = match representation {
            ClientResponseRepresentation::Json { media_type, .. }
            | ClientResponseRepresentation::Text { media_type }
            | ClientResponseRepresentation::BinaryBuffered { media_type, .. } => {
                (RequestDiscriminatorTransport::Buffered, Some(media_type.as_str()))
            }
            ClientResponseRepresentation::EventStream { media_type } => (
                RequestDiscriminatorTransport::EventStream,
                Some(media_type.as_str()),
            ),
            ClientResponseRepresentation::BinaryStream { media_type, .. } => (
                RequestDiscriminatorTransport::BinaryStream,
                Some(media_type.as_str()),
            ),
            ClientResponseRepresentation::Empty => (RequestDiscriminatorTransport::Buffered, None),
        };
        candidate_transport == transport
            && candidate_media_type.is_some_and(|candidate| {
                candidate.trim().eq_ignore_ascii_case(media_type.trim())
            })
    }

    fn request_discriminator_value_is_compatible(
        value: &RequestDiscriminatorValue,
        schema_type: &crate::analysis::SchemaType,
        analysis: &SchemaAnalysis,
        visited: &mut std::collections::HashSet<String>,
    ) -> bool {
        use crate::analysis::SchemaType;
        match schema_type {
            SchemaType::Primitive { rust_type, .. } => match value {
                RequestDiscriminatorValue::Bool(_) => rust_type == "bool",
                RequestDiscriminatorValue::Integer(_) => matches!(
                    rust_type.as_str(),
                    "i8" | "i16" | "i32" | "i64" | "isize" | "u8" | "u16" | "u32" | "u64" | "usize"
                ),
                RequestDiscriminatorValue::String(_) => rust_type == "String" || rust_type == "str",
            },
            SchemaType::Reference { target } => {
                if !visited.insert(target.clone()) {
                    return false;
                }
                let compatible = analysis.schemas.get(target).is_some_and(|schema| {
                    Self::request_discriminator_value_is_compatible(
                        value,
                        &schema.schema_type,
                        analysis,
                        visited,
                    )
                });
                visited.remove(target);
                compatible
            }
            SchemaType::Nullable { inner_type } => Self::request_discriminator_value_is_compatible(
                value,
                inner_type,
                analysis,
                visited,
            ),
            SchemaType::StringEnum { values } => matches!(
                value,
                RequestDiscriminatorValue::String(value) if values.contains(value)
            ),
            SchemaType::ExtensibleEnum { .. } => matches!(value, RequestDiscriminatorValue::String(_)),
            _ => false,
        }
    }
''',
)

# Extend body-model planning to project every emitted field exactly once.
text = Path("src/client_generator.rs").read_text()
text = text.replace(
    '''                    required_construction: RequiredBodyConstruction::Whole,
                    optional_fields: Vec::new(),
''',
    '''                    required_construction: RequiredBodyConstruction::Whole,
                    all_fields: Vec::new(),
                    optional_fields: Vec::new(),
'''
)
text = text.replace(
    '''                required_construction: RequiredBodyConstruction::Whole,
                optional_fields: Vec::new(),
''',
    '''                required_construction: RequiredBodyConstruction::Whole,
                all_fields: Vec::new(),
                optional_fields: Vec::new(),
'''
)
old = '''        let mut optional_fields = Vec::new();
        let mut stack = std::collections::HashSet::new();
        self.collect_optional_body_fields(
            resolved_name,
            Vec::new(),
            analysis,
            &mut stack,
            &mut optional_fields,
        );
'''
new = '''        let mut all_fields = Vec::new();
        let mut stack = std::collections::HashSet::new();
        self.collect_body_fields(
            resolved_name,
            Vec::new(),
            analysis,
            &mut stack,
            &mut all_fields,
        );
        let optional_fields = all_fields
            .iter()
            .filter(|field| !field.is_required)
            .cloned()
            .collect();
'''
if old not in text:
    raise SystemExit("missing body field collection anchor")
text = text.replace(old, new, 1)
old = '''        Some(BodyModelPlan {
            body_ident,
            body_type: quote! { #body_type },
            required_construction,
            optional_fields,
        })
'''
new = '''        Some(BodyModelPlan {
            body_ident,
            body_type: quote! { #body_type },
            required_construction,
            all_fields,
            optional_fields,
        })
'''
if old not in text:
    raise SystemExit("missing BodyModelPlan final anchor")
text = text.replace(old, new, 1)
text = text.replace("fn collect_optional_body_fields(", "fn collect_body_fields(", 1)
text = text.replace("self.collect_optional_body_fields(", "self.collect_body_fields(")
old = '''                for field in self.emitted_object_properties(
                    schema_name,
                    properties,
                    required,
                    additional_properties,
                    analysis,
                ) {
                    if field.is_required {
                        continue;
                    }
                    let mut field_path = access_path.clone();
                    field_path.push(field.ident.clone());
                    output.push(BodyFieldPlan {
                        wire_name: field.wire_name.to_string(),
                        preferred_method_name: field.ident.to_string(),
                        value_ident: field.ident.clone(),
                        value_type: self.generate_property_base_type(
                            schema_name,
                            field.wire_name,
                            field.property,
                            analysis,
                        ),
                        access_path: field_path,
                        tri_state: self.property_is_tri_state(
                            schema_name,
                            field.wire_name,
                            field.property,
                            field.is_required,
                        ),
                    });
                }
'''
new = '''                for field in self.emitted_object_properties(
                    schema_name,
                    properties,
                    required,
                    additional_properties,
                    analysis,
                ) {
                    let mut field_path = access_path.clone();
                    field_path.push(field.ident.clone());
                    output.push(BodyFieldPlan {
                        wire_name: field.wire_name.to_string(),
                        preferred_method_name: field.ident.to_string(),
                        value_ident: field.ident.clone(),
                        value_type: self.generate_property_base_type(
                            schema_name,
                            field.wire_name,
                            field.property,
                            analysis,
                        ),
                        access_path: field_path,
                        is_required: field.is_required,
                        nullable: self.property_is_nullable(
                            schema_name,
                            field.wire_name,
                            field.property,
                        ),
                        tri_state: self.property_is_tri_state(
                            schema_name,
                            field.wire_name,
                            field.property,
                            field.is_required,
                        ),
                        schema_type: field.property.schema_type.clone(),
                    });
                }
'''
if old not in text:
    raise SystemExit("missing body field emission anchor")
text = text.replace(old, new, 1)
Path("src/client_generator.rs").write_text(text)

# Builder destructuring now ignores the all-fields projection explicitly.
replace_once(
    "src/client_generator.rs",
    '''                required_construction,
                optional_fields,
            } = body_plan;
''',
    '''                required_construction,
                all_fields: _,
                optional_fields,
            } = body_plan;
''',
)

# Emit assignments before request serialization.
replace_once(
    "src/client_generator.rs",
    '''        let request_body = self.generate_request_body(op, analysis, with_multipart_filenames);
        let query_params = self.generate_query_params(op);
''',
    '''        let request_body = self.generate_request_body(op, analysis, with_multipart_filenames);
        let request_discriminators =
            Self::generate_request_discriminator_assignments(call_shape);
        let query_params = self.generate_query_params(op);
''',
)
replace_once(
    "src/client_generator.rs",
    '''                let mut req = #http_method_call;
                #request_body

                #query_params
''',
    '''                let mut req = #http_method_call;
                #request_discriminators
                #request_body

                #query_params
''',
)

# Add the rendering helper immediately before auth handling.
replace_once(
    "src/client_generator.rs",
    '''    /// T3: emit the auth-token application based on the configured AuthConfig.
''',
    '''    fn generate_request_discriminator_assignments(
        call_shape: &ClientCallShapePlan,
    ) -> TokenStream {
        if call_shape.request_discriminators.is_empty() {
            return TokenStream::new();
        }

        let assignments = call_shape.request_discriminators.iter().map(|plan| {
            let value_type = match syn::parse_str::<syn::Type>(&plan.rust_value_type) {
                Ok(value_type) => value_type,
                Err(error) => return error.to_compile_error(),
            };
            let mut target = quote! { request };
            for access in &plan.rust_access_path {
                let access = match syn::parse_str::<syn::Ident>(access) {
                    Ok(access) => access,
                    Err(error) => return error.to_compile_error(),
                };
                target = quote! { #target.#access };
            }
            let value = match &plan.value {
                RequestDiscriminatorValue::Bool(value) => {
                    quote! { serde_json::Value::Bool(#value) }
                }
                RequestDiscriminatorValue::Integer(value) => {
                    quote! { serde_json::Value::Number(serde_json::Number::from(#value)) }
                }
                RequestDiscriminatorValue::String(value) => {
                    quote! { serde_json::Value::String(#value.to_string()) }
                }
            };
            let assignment = if plan.field_tri_state {
                quote! { #target = Some(Some(__request_discriminator_value)); }
            } else if !plan.field_required || plan.field_nullable {
                quote! { #target = Some(__request_discriminator_value); }
            } else {
                quote! { #target = __request_discriminator_value; }
            };
            quote! {
                {
                    let __request_discriminator_value: #value_type =
                        serde_json::from_value(#value)
                            .map_err(HttpError::serialization_error)?;
                    #assignment
                }
            }
        });

        quote! {
            let mut request = request;
            #(#assignments)*
        }
    }

    /// T3: emit the auth-token application based on the configured AuthConfig.
''',
)

# The complete HTTP-client path validates before emitting any source.
replace_once(
    "src/generator.rs",
    '''    ) -> Result<String> {
        let provenance_attribute = self.provenance_attribute();
''',
    '''    ) -> Result<String> {
        self.validate_client_request_discriminators(analysis, operations)?;
        let provenance_attribute = self.provenance_attribute();
''',
)

# --- Generic fixture -------------------------------------------------------
Path("tests/client_request_discriminator_test.rs").write_text(r'''use openapi_to_rust::client_generator::{
    ClientResponseRepresentation, ClientRequestDiscriminatorPlan,
};
use openapi_to_rust::config::{
    ClientSection, RequestDiscriminatorRule, RequestDiscriminatorTransport,
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
        .find(|plan| matches!(plan.representation, ClientResponseRepresentation::Json { .. }))
        .expect("JSON call shape");
    assert_eq!(json.request_discriminators.len(), 1);
    assert_eq!(json.request_discriminators[0].wire_name, "live-output");
    assert_eq!(
        json.request_discriminators[0].value,
        RequestDiscriminatorValue::Bool(false)
    );

    let sse = render
        .iter()
        .find(|plan| matches!(plan.representation, ClientResponseRepresentation::EventStream { .. }))
        .expect("SSE call shape");
    assert_eq!(sse.request_discriminators.len(), 2);
    assert!(sse.request_discriminators.iter().any(|plan| {
        plan.wire_name == "live-output"
            && plan.value == RequestDiscriminatorValue::Bool(true)
    }));
    assert!(sse.request_discriminators.iter().any(|plan| {
        plan.wire_name == "response-mode"
            && plan.value == RequestDiscriminatorValue::String("live-events".to_string())
    }));

    let client = generator.generate_http_client(&analysis)?;
    let sse_start = client.find("pub async fn render_stream(").expect("SSE method");
    let sse_body = &client[sse_start..];
    let mutation = sse_body.find("let mut request = request;").expect("request mutation");
    let serialization = sse_body.find(".json(&request)").expect("request serialization");
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
    assert_validation_error(vec![duplicate.clone(), duplicate], "duplicate request discriminator");
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
''')
