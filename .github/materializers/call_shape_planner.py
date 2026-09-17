from pathlib import Path

path = Path("src/client_generator.rs")
text = path.read_text()

def replace_between(source: str, start: str, end: str, replacement: str) -> str:
    start_i = source.index(start)
    end_i = source.index(end, start_i)
    return source[:start_i] + replacement + source[end_i:]

old_import = "use crate::analysis::{OperationInfo, OperationResponseBody, ParameterInfo, SchemaAnalysis};"
new_import = '''use crate::analysis::{
    OperationInfo, OperationResponseBody, OperationResponseRepresentation, ParameterInfo,
    SchemaAnalysis,
};'''
assert old_import in text
text = text.replace(old_import, new_import, 1)

defs_start = "#[derive(Clone, Copy)]\nenum ClientSuccessBody"
defs_end = "\nimpl CodeGenerator {"
new_defs = r'''#[derive(Clone, Copy)]
enum ClientSuccessBody<'a> {
    Json(&'a str),
    Text,
    Binary,
    EventStream,
    Empty,
}

/// Semantic identity of one generated response call shape.
///
/// The generated Rust method name is deliberately stored separately on
/// [`ClientCallShapePlan`]. Consumers must use this identity rather than infer
/// transport semantics from method suffixes.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ClientResponseRepresentation {
    Json {
        schema_name: String,
        media_type: String,
    },
    Text {
        media_type: String,
    },
    BinaryBuffered {
        media_type: String,
        wildcard: bool,
    },
    EventStream {
        media_type: String,
    },
    BinaryStream {
        media_type: String,
        wildcard: bool,
    },
    Empty,
}

impl ClientResponseRepresentation {
    fn success_body(&self) -> ClientSuccessBody<'_> {
        match self {
            Self::Json { schema_name, .. } => ClientSuccessBody::Json(schema_name),
            Self::Text { .. } => ClientSuccessBody::Text,
            Self::BinaryBuffered { .. } | Self::BinaryStream { .. } => {
                ClientSuccessBody::Binary
            }
            Self::EventStream { .. } => ClientSuccessBody::EventStream,
            Self::Empty => ClientSuccessBody::Empty,
        }
    }

    fn accept_media_type(&self) -> Option<&str> {
        match self {
            Self::Json { media_type, .. }
            | Self::Text { media_type }
            | Self::EventStream { media_type } => Some(media_type),
            Self::BinaryBuffered {
                media_type,
                wildcard,
            }
            | Self::BinaryStream {
                media_type,
                wildcard,
            } => (!wildcard).then_some(media_type.as_str()),
            Self::Empty => None,
        }
    }

    fn is_streaming(&self) -> bool {
        matches!(self, Self::EventStream { .. } | Self::BinaryStream { .. })
    }
}

/// Stable OpenAPI identity for a generated operation.
///
/// `operation_id` is the source document's operationId before the analyzer's
/// collision-safe emitted-ID allocation. Method and path disambiguate duplicate
/// or otherwise invalid real-world operationIds without depending on Rust names.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, serde::Serialize)]
pub struct SourceOperationIdentity {
    pub operation_id: String,
    pub method: String,
    pub path: String,
}

/// Shared pre-render plan for one generated client call shape.
///
/// Source rendering and generator-owned binding metadata consume this same
/// object so naming, response representation and success-type decisions are
/// made once.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct ClientCallShapePlan {
    pub source_operation: SourceOperationIdentity,
    pub emitted_operation_id: String,
    pub rust_method_name: String,
    pub representation: ClientResponseRepresentation,
    pub success_statuses: Vec<String>,
    pub success_type: String,
}

#[derive(Clone)]
struct ClientSuccessSelection {
    statuses: Vec<String>,
    representation: ClientResponseRepresentation,
}

enum RequiredBodyConstruction {
    Default,
    New(Vec<BodyConstructorParam>),
    Whole,
}

struct BodyConstructorParam {
    preferred_ident: syn::Ident,
    value_type: TokenStream,
}

struct BodyModelPlan {
    body_ident: syn::Ident,
    body_type: TokenStream,
    required_construction: RequiredBodyConstruction,
    optional_fields: Vec<BodyFieldPlan>,
}

#[derive(Clone)]
struct ClientOperationMethodPlan<'a> {
    operation: &'a OperationInfo,
    call_shapes: Vec<ClientCallShapePlan>,
    multipart_filename_method_name: Option<syn::Ident>,
}
'''
text = replace_between(text, defs_start, defs_end, new_defs)

alias_start = "    pub(crate) fn generate_http_response_stream_type_alias("
alias_end = "    /// Generate the HTTP client struct with middleware support"
new_alias = r'''    pub(crate) fn generate_http_response_stream_type_alias(
        &self,
        analysis: &SchemaAnalysis,
        operations: &[&OperationInfo],
    ) -> TokenStream {
        let plans = self.plan_client_operation_methods(analysis, operations);
        let has_streaming_response = plans
            .iter()
            .flat_map(|plan| &plan.call_shapes)
            .any(|shape| shape.representation.is_streaming());
        if !has_streaming_response {
            return quote! {};
        }

        quote! {
            /// Owned byte stream returned by streaming HTTP responses.
            #[cfg(not(target_arch = "wasm32"))]
            pub type HttpResponseByteStream = futures_util::stream::BoxStream<
                'static,
                Result<bytes::Bytes, reqwest::Error>,
            >;

            /// Owned byte stream returned by streaming HTTP responses.
            #[cfg(target_arch = "wasm32")]
            pub type HttpResponseByteStream = futures_util::stream::LocalBoxStream<
                'static,
                Result<bytes::Bytes, reqwest::Error>,
            >;
        }
    }

'''
text = replace_between(text, alias_start, alias_end, new_alias)

planner_start = "    fn plan_client_operation_methods<'a>("
planner_end = "    fn generate_operation_builders("
new_planner = r'''    /// Return the exact call-shape plan used by the low-level all-operations
    /// client renderer.
    ///
    /// This additive library seam is intentionally transport-focused. Public
    /// SDK naming and hierarchy do not belong here.
    pub fn plan_client_call_shapes(&self, analysis: &SchemaAnalysis) -> Vec<ClientCallShapePlan> {
        let operations: Vec<&OperationInfo> = analysis.operations.values().collect();
        self.plan_client_operation_methods(analysis, &operations)
            .into_iter()
            .flat_map(|plan| plan.call_shapes)
            .collect()
    }

    fn plan_client_operation_methods<'a>(
        &self,
        analysis: &'a SchemaAnalysis,
        operations: &[&'a OperationInfo],
    ) -> Vec<ClientOperationMethodPlan<'a>> {
        let mut used_method_names: std::collections::HashSet<String> = operations
            .iter()
            .map(|operation| self.get_method_name(operation).to_string())
            .collect();

        operations
            .iter()
            .map(|operation| {
                let operation = *operation;
                let method_name = self.get_method_name(operation);
                let multipart_filename_method_name = matches!(
                    operation.request_body.as_ref(),
                    Some(crate::analysis::RequestBodyContent::Multipart { .. })
                )
                .then(|| {
                    let preferred = format!("{method_name}_with_multipart_filenames");
                    let allocated = Self::allocate_name(&preferred, &mut used_method_names);
                    Self::to_field_ident(&allocated)
                });
                let call_shapes = self.plan_response_call_shapes(
                    analysis,
                    operation,
                    &method_name.to_string(),
                    &mut used_method_names,
                );
                ClientOperationMethodPlan {
                    operation,
                    call_shapes,
                    multipart_filename_method_name,
                }
            })
            .collect()
    }

    fn plan_response_call_shapes(
        &self,
        analysis: &SchemaAnalysis,
        operation: &OperationInfo,
        base_method_name: &str,
        used_method_names: &mut std::collections::HashSet<String>,
    ) -> Vec<ClientCallShapePlan> {
        let base = self.get_success_response(analysis, operation);
        let mut call_shapes = Vec::new();
        let base_shape = self.build_call_shape_plan(
            analysis,
            operation,
            base_method_name.to_string(),
            base.representation.clone(),
            base.statuses.clone(),
        );
        call_shapes.push(base_shape.clone());

        if matches!(
            base_shape.representation,
            ClientResponseRepresentation::BinaryBuffered { .. }
        ) {
            self.push_binary_stream_shape(
                analysis,
                operation,
                &base_shape,
                used_method_names,
                &mut call_shapes,
            );
        }

        let candidates = self.success_response_candidates(analysis, operation);
        let selected_response = candidates
            .iter()
            .find(|(_, response)| {
                Self::preferred_response_representation(response) == base.representation
            })
            .map(|(_, response)| *response);

        if let Some(response) = selected_response {
            for representation in response
                .representations
                .iter()
                .map(Self::response_representation_from_inventory)
            {
                if representation == base.representation
                    || call_shapes
                        .iter()
                        .any(|shape| shape.representation == representation)
                {
                    continue;
                }

                let statuses: Vec<String> = candidates
                    .iter()
                    .filter_map(|(status, candidate)| {
                        Self::response_has_representation(candidate, &representation)
                            .then_some((*status).to_string())
                    })
                    .collect();
                if statuses.is_empty() {
                    continue;
                }

                let preferred =
                    Self::preferred_alternate_method_name(base_method_name, &representation);
                let method_name = Self::allocate_name(&preferred, used_method_names);
                let shape = self.build_call_shape_plan(
                    analysis,
                    operation,
                    method_name,
                    representation,
                    statuses,
                );
                call_shapes.push(shape.clone());

                if matches!(
                    shape.representation,
                    ClientResponseRepresentation::BinaryBuffered { .. }
                ) {
                    self.push_binary_stream_shape(
                        analysis,
                        operation,
                        &shape,
                        used_method_names,
                        &mut call_shapes,
                    );
                }
            }
        }

        call_shapes
    }

    fn push_binary_stream_shape(
        &self,
        analysis: &SchemaAnalysis,
        operation: &OperationInfo,
        buffered_shape: &ClientCallShapePlan,
        used_method_names: &mut std::collections::HashSet<String>,
        call_shapes: &mut Vec<ClientCallShapePlan>,
    ) {
        let ClientResponseRepresentation::BinaryBuffered {
            media_type,
            wildcard,
        } = &buffered_shape.representation
        else {
            return;
        };
        let representation = ClientResponseRepresentation::BinaryStream {
            media_type: media_type.clone(),
            wildcard: *wildcard,
        };
        if call_shapes
            .iter()
            .any(|shape| shape.representation == representation)
        {
            return;
        }
        let preferred = format!("{}_stream", buffered_shape.rust_method_name);
        let method_name = Self::allocate_name(&preferred, used_method_names);
        call_shapes.push(self.build_call_shape_plan(
            analysis,
            operation,
            method_name,
            representation,
            buffered_shape.success_statuses.clone(),
        ));
    }

    fn build_call_shape_plan(
        &self,
        analysis: &SchemaAnalysis,
        operation: &OperationInfo,
        rust_method_name: String,
        representation: ClientResponseRepresentation,
        success_statuses: Vec<String>,
    ) -> ClientCallShapePlan {
        ClientCallShapePlan {
            source_operation: Self::source_operation_identity(analysis, operation),
            emitted_operation_id: operation.operation_id.clone(),
            success_type: self.success_type_name(&representation),
            rust_method_name,
            representation,
            success_statuses,
        }
    }

    fn source_operation_identity(
        analysis: &SchemaAnalysis,
        operation: &OperationInfo,
    ) -> SourceOperationIdentity {
        let mut source_ids = analysis.operation_id_aliases.iter().filter_map(
            |(source_operation_id, emitted_operation_ids)| {
                emitted_operation_ids
                    .iter()
                    .any(|operation_id| operation_id == &operation.operation_id)
                    .then_some(source_operation_id)
            },
        );
        let operation_id = source_ids
            .next()
            .cloned()
            .unwrap_or_else(|| operation.operation_id.clone());
        debug_assert!(
            source_ids.next().is_none(),
            "one emitted operation must map to at most one source operationId"
        );
        SourceOperationIdentity {
            operation_id,
            method: operation.method.clone(),
            path: operation.path.clone(),
        }
    }

    fn preferred_alternate_method_name(
        base_method_name: &str,
        representation: &ClientResponseRepresentation,
    ) -> String {
        let suffix = match representation {
            ClientResponseRepresentation::Json { media_type, .. } => {
                format!("json_{}", Self::response_media_suffix(media_type))
            }
            ClientResponseRepresentation::Text { .. } => "text".to_string(),
            ClientResponseRepresentation::BinaryBuffered { media_type, .. } => {
                Self::response_media_suffix(media_type)
            }
            ClientResponseRepresentation::EventStream { .. } => "stream".to_string(),
            ClientResponseRepresentation::BinaryStream { media_type, .. } => {
                format!("{}_stream", Self::response_media_suffix(media_type))
            }
            ClientResponseRepresentation::Empty => "empty".to_string(),
        };
        format!("{base_method_name}_{suffix}")
    }

    fn response_media_suffix(media_type: &str) -> String {
        let essence = media_type.split(';').next().unwrap_or(media_type).trim();
        let subtype = essence
            .split_once('/')
            .map(|(_, subtype)| subtype)
            .unwrap_or(essence);
        if subtype == "*" || subtype.eq_ignore_ascii_case("octet-stream") {
            return "binary".to_string();
        }
        let normalized: String = subtype
            .chars()
            .map(|character| {
                if character.is_ascii_alphanumeric() {
                    character
                } else {
                    '_'
                }
            })
            .collect();
        let suffix = normalized.to_snake_case();
        if suffix.is_empty() {
            "response".to_string()
        } else {
            suffix
        }
    }

'''
text = replace_between(text, planner_start, planner_end, new_planner)

methods_start = "    /// Generate a single operation method.\n"
methods_end = "    /// T3: emit the auth-token application based on the configured AuthConfig."
new_methods = r'''    /// Generate every planned call shape for a single source operation.
    ///
    /// Multipart operations also get an additive per-call filename variant for
    /// the base response shape so callers can assign independent filenames
    /// without mutating client state.
    fn generate_single_operation_method(
        &self,
        analysis: &SchemaAnalysis,
        plan: &ClientOperationMethodPlan<'_>,
    ) -> TokenStream {
        let op = plan.operation;
        let mut methods: Vec<TokenStream> = plan
            .call_shapes
            .iter()
            .map(|call_shape| {
                self.generate_single_operation_method_variant(
                    analysis,
                    op,
                    call_shape,
                    Self::to_field_ident(&call_shape.rust_method_name),
                    false,
                )
            })
            .collect();

        if let (Some(filename_method), Some(base_shape)) = (
            &plan.multipart_filename_method_name,
            plan.call_shapes.first(),
        ) {
            methods.push(self.generate_single_operation_method_variant(
                analysis,
                op,
                base_shape,
                filename_method.clone(),
                true,
            ));
        }

        quote! { #(#methods)* }
    }

    fn generate_single_operation_method_variant(
        &self,
        analysis: &SchemaAnalysis,
        op: &OperationInfo,
        call_shape: &ClientCallShapePlan,
        method_name: syn::Ident,
        with_multipart_filenames: bool,
    ) -> TokenStream {
        let http_method_call = self.http_method_call(op);
        let path = &op.path;
        let request_param = self.generate_request_param(op);
        let request_params = if with_multipart_filenames {
            if request_param.is_empty() {
                quote! { multipart_filenames: &[(&str, &str)] }
            } else {
                quote! { #request_param, multipart_filenames: &[(&str, &str)] }
            }
        } else {
            request_param
        };
        let request_body = self.generate_request_body(op, analysis, with_multipart_filenames);
        let query_params = self.generate_query_params(op);
        let header_params = self.generate_header_params(op);
        let cookie_params = self.generate_cookie_params(op);
        let auth_application = self.generate_auth_application();
        let response_type: syn::Type = syn::parse_str(&call_shape.success_type)
            .expect("planned client success type must be valid Rust");
        let op_error_type = self.op_error_type_token(op);
        let accept = call_shape.representation.accept_media_type();
        let error_handling = self.generate_error_handling(
            op,
            &call_shape.representation,
            &call_shape.success_statuses,
        );
        let (custom_headers, accept_header) = if let Some(media_type) = accept {
            (
                quote! {
                    for (name, value) in &self.custom_headers {
                        if !name.eq_ignore_ascii_case("accept") {
                            req = req.header(name, value);
                        }
                    }
                },
                quote! {
                    req = req.header(reqwest::header::ACCEPT, #media_type);
                },
            )
        } else {
            (
                quote! {
                    for (name, value) in &self.custom_headers {
                        req = req.header(name, value);
                    }
                },
                TokenStream::new(),
            )
        };
        let url_construction = self.generate_url_construction(path, op);
        let doc_comment = self.generate_operation_doc_comment(op);
        let filename_doc = with_multipart_filenames.then(|| {
            quote! {
                /// Override multipart filenames for binary fields by OpenAPI wire name.
                /// Unspecified binary fields retain the base method's no-filename behavior.
            }
        });
        let representation_doc = match &call_shape.representation {
            ClientResponseRepresentation::BinaryStream { .. } => Some(quote! {
                /// Stream the selected successful binary response body without buffering it.
            }),
            ClientResponseRepresentation::EventStream { .. } => Some(quote! {
                /// Stream the selected server-sent event response body.
            }),
            _ => None,
        };

        quote! {
            #doc_comment
            #filename_doc
            #representation_doc
            pub async fn #method_name(
                &self,
                #request_params
            ) -> Result<#response_type, ApiOpError<#op_error_type>> {
                #url_construction

                let mut req = #http_method_call;
                #request_body

                #query_params
                #header_params
                #cookie_params
                #auth_application
                #custom_headers
                #accept_header

                let response = req.send().await?;
                #error_handling
            }
        }
    }

'''
text = replace_between(text, methods_start, methods_end, new_methods)

success_start = "    /// Find the success (2xx) response schema name, if any."
success_end = "    fn success_status_guard("
new_success = r'''    /// Find the success (2xx) response schema name, if any.
    ///
    /// Only considers 2xx status codes. Error schemas (4xx, 5xx) are ignored
    /// so that endpoints like 204 No Content correctly return `()` instead of
    /// accidentally picking up the error schema.
    fn get_success_response_schema<'a>(
        &self,
        op: &'a OperationInfo,
    ) -> Option<(&'a str, &'a String)> {
        op.response_schemas
            .get_key_value("200")
            .or_else(|| op.response_schemas.get_key_value("201"))
            .or_else(|| {
                op.response_schemas
                    .iter()
                    .find(|(code, _)| code.starts_with('2'))
            })
            .map(|(status, schema)| (status.as_str(), schema))
    }

    fn success_response_candidates<'a>(
        &self,
        analysis: &'a SchemaAnalysis,
        op: &OperationInfo,
    ) -> Vec<(&'a str, &'a crate::analysis::OperationResponse)> {
        let Some(responses) = analysis.operation_responses.get(&op.operation_id) else {
            return Vec::new();
        };
        let mut candidates = Vec::new();
        for preferred in ["200", "201"] {
            if let Some((status, response)) = responses.get_key_value(preferred) {
                candidates.push((status.as_str(), response));
            }
        }
        candidates.extend(
            responses
                .iter()
                .filter(|(status, _)| {
                    status.starts_with('2')
                        && status.as_str() != "200"
                        && status.as_str() != "201"
                })
                .map(|(status, response)| (status.as_str(), response)),
        );
        candidates
    }

    fn get_success_response(
        &self,
        analysis: &SchemaAnalysis,
        op: &OperationInfo,
    ) -> ClientSuccessSelection {
        let candidates = self.success_response_candidates(analysis, op);
        let selected = candidates
            .iter()
            .copied()
            .find(|(_, response)| {
                matches!(
                    Self::preferred_response_representation(response).success_body(),
                    ClientSuccessBody::Json(_)
                        | ClientSuccessBody::Text
                        | ClientSuccessBody::Binary
                )
            })
            .or_else(|| {
                candidates.iter().copied().find(|(_, response)| {
                    matches!(
                        Self::preferred_response_representation(response).success_body(),
                        ClientSuccessBody::EventStream
                    )
                })
            })
            .or_else(|| candidates.first().copied());

        if let Some((_, response)) = selected {
            let representation = Self::preferred_response_representation(response);
            let body = representation.success_body();
            let statuses = candidates
                .iter()
                .filter_map(|(status, candidate)| {
                    Self::success_bodies_are_compatible(
                        body,
                        Self::preferred_response_representation(candidate).success_body(),
                    )
                    .then_some((*status).to_string())
                })
                .collect();
            return ClientSuccessSelection {
                statuses,
                representation,
            };
        }

        if let Some((_status, schema_name)) = self.get_success_response_schema(op) {
            let statuses = op
                .response_schemas
                .iter()
                .filter_map(|(candidate_status, candidate_schema)| {
                    (candidate_status.starts_with('2') && candidate_schema == schema_name)
                        .then_some(candidate_status.clone())
                })
                .collect();
            ClientSuccessSelection {
                statuses,
                representation: ClientResponseRepresentation::Json {
                    schema_name: schema_name.clone(),
                    media_type: "application/json".to_string(),
                },
            }
        } else if Self::returns_raw_event_stream(op) {
            ClientSuccessSelection {
                statuses: Vec::new(),
                representation: ClientResponseRepresentation::EventStream {
                    media_type: "text/event-stream".to_string(),
                },
            }
        } else {
            ClientSuccessSelection {
                statuses: Vec::new(),
                representation: ClientResponseRepresentation::Empty,
            }
        }
    }

    fn preferred_response_representation(
        response: &crate::analysis::OperationResponse,
    ) -> ClientResponseRepresentation {
        match &response.body {
            Some(OperationResponseBody::Json {
                schema_name,
                media_type,
            }) => ClientResponseRepresentation::Json {
                schema_name: schema_name.clone(),
                media_type: media_type.clone(),
            },
            Some(OperationResponseBody::Text { media_type }) => {
                ClientResponseRepresentation::Text {
                    media_type: media_type.clone(),
                }
            }
            Some(OperationResponseBody::Binary {
                media_type,
                wildcard,
            }) => ClientResponseRepresentation::BinaryBuffered {
                media_type: media_type.clone(),
                wildcard: *wildcard,
            },
            None if response.schema_name.is_some() => ClientResponseRepresentation::Json {
                schema_name: response.schema_name.clone().unwrap_or_default(),
                media_type: response
                    .media_type
                    .clone()
                    .unwrap_or_else(|| "application/json".to_string()),
            },
            None if response.supports_streaming => ClientResponseRepresentation::EventStream {
                media_type: "text/event-stream".to_string(),
            },
            None => ClientResponseRepresentation::Empty,
        }
    }

    fn response_representation_from_inventory(
        representation: &OperationResponseRepresentation,
    ) -> ClientResponseRepresentation {
        match representation {
            OperationResponseRepresentation::Json {
                schema_name,
                media_type,
            } => ClientResponseRepresentation::Json {
                schema_name: schema_name.clone(),
                media_type: media_type.clone(),
            },
            OperationResponseRepresentation::Text { media_type } => {
                ClientResponseRepresentation::Text {
                    media_type: media_type.clone(),
                }
            }
            OperationResponseRepresentation::Binary {
                media_type,
                wildcard,
            } => ClientResponseRepresentation::BinaryBuffered {
                media_type: media_type.clone(),
                wildcard: *wildcard,
            },
            OperationResponseRepresentation::EventStream { media_type } => {
                ClientResponseRepresentation::EventStream {
                    media_type: media_type.clone(),
                }
            }
        }
    }

    fn response_has_representation(
        response: &crate::analysis::OperationResponse,
        representation: &ClientResponseRepresentation,
    ) -> bool {
        let buffered_representation = match representation {
            ClientResponseRepresentation::BinaryStream {
                media_type,
                wildcard,
            } => ClientResponseRepresentation::BinaryBuffered {
                media_type: media_type.clone(),
                wildcard: *wildcard,
            },
            other => other.clone(),
        };
        Self::preferred_response_representation(response) == buffered_representation
            || response
                .representations
                .iter()
                .map(Self::response_representation_from_inventory)
                .any(|candidate| candidate == buffered_representation)
    }

    fn success_bodies_are_compatible(
        selected: ClientSuccessBody<'_>,
        candidate: ClientSuccessBody<'_>,
    ) -> bool {
        match (selected, candidate) {
            (ClientSuccessBody::Json(selected), ClientSuccessBody::Json(candidate)) => {
                selected == candidate
            }
            (ClientSuccessBody::Text, ClientSuccessBody::Text)
            | (ClientSuccessBody::Binary, ClientSuccessBody::Binary)
            | (ClientSuccessBody::EventStream, ClientSuccessBody::EventStream)
            | (ClientSuccessBody::Empty, ClientSuccessBody::Empty) => true,
            _ => false,
        }
    }

    fn success_type_name(&self, representation: &ClientResponseRepresentation) -> String {
        match representation {
            ClientResponseRepresentation::Json { schema_name, .. } => {
                self.to_rust_type_name(schema_name)
            }
            ClientResponseRepresentation::Text { .. } => "String".to_string(),
            ClientResponseRepresentation::BinaryBuffered { .. } => "bytes::Bytes".to_string(),
            ClientResponseRepresentation::EventStream { .. }
            | ClientResponseRepresentation::BinaryStream { .. } => {
                "HttpResponseByteStream".to_string()
            }
            ClientResponseRepresentation::Empty => "()".to_string(),
        }
    }

'''
text = replace_between(text, success_start, success_end, new_success)
text = text.replace(
    "    fn success_status_guard(statuses: &[&str]) -> TokenStream {",
    "    fn success_status_guard(statuses: &[String]) -> TokenStream {",
    1,
)

error_start = "    fn generate_error_handling(\n"
error_end = "    /// Generate the match arms that select which per-op error variant to"
new_error = r'''    fn generate_error_handling(
        &self,
        op: &OperationInfo,
        representation: &ClientResponseRepresentation,
        success_statuses: &[String],
    ) -> TokenStream {
        let op_error_type = self.op_error_type_token(op);
        let success_body = representation.success_body();
        let success_status_guard = Self::success_status_guard(success_statuses);
        let selected_status = if success_statuses.is_empty() {
            "any declared 2xx response".to_string()
        } else {
            success_statuses.join(", ")
        };

        let success_branch = match success_body {
            ClientSuccessBody::Json(_) => quote! {
                match serde_json::from_str(&body_text) {
                    Ok(body) => Ok(body),
                    Err(e) => Err(ApiOpError::Api(ApiError {
                        status: status_code,
                        headers: headers,
                        body: body_text,
                        raw_body,
                        typed: None,
                        parse_error: Some(format!(
                            "failed to deserialize 2xx response body: {}",
                            e
                        )),
                    })),
                }
            },
            ClientSuccessBody::Text => quote! {
                let _ = raw_body;
                Ok(body_text)
            },
            ClientSuccessBody::Empty => quote! {
                let _ = body_text;
                let _ = raw_body;
                let _ = headers;
                Ok(())
            },
            ClientSuccessBody::Binary | ClientSuccessBody::EventStream => quote! {},
        };

        let error_match_arms = self.generate_error_match_arms(op);

        // Streaming success paths hand back the live byte stream instead of
        // buffering it. The representation identity — never the Rust method
        // name — decides whether a call shape streams.
        if representation.is_streaming() {
            return quote! {
                let status = response.status();
                let status_code = status.as_u16();
                let headers = response.headers().clone();

                if #success_status_guard {
                    Ok(Box::pin(response.bytes_stream()))
                } else {
                    if status.is_success() {
                        return Err(ApiOpError::Api(ApiError {
                            status: status_code,
                            headers,
                            body: String::new(),
                            raw_body: Vec::new(),
                            typed: None,
                            parse_error: Some(format!(
                                "unexpected successful status {}; generated return type selects `{}`; live response body was not buffered",
                                status_code,
                                #selected_status,
                            )),
                        }));
                    }
                    let body_bytes = __read_bounded_response_body(
                        response,
                        self.max_response_body_bytes,
                    ).await?;
                    let raw_body = body_bytes;
                    let body_text = String::from_utf8_lossy(&raw_body).into_owned();
                    let typed: Option<#op_error_type>;
                    let parse_error: Option<String>;
                    #error_match_arms
                    Err(ApiOpError::Api(ApiError {
                        status: status_code,
                        headers,
                        body: body_text,
                        raw_body,
                        typed,
                        parse_error,
                    }))
                }
            };
        }

        if matches!(
            representation,
            ClientResponseRepresentation::BinaryBuffered { .. }
        ) {
            return quote! {
                let status = response.status();
                let status_code = status.as_u16();
                let headers = response.headers().clone();

                let body_bytes = __read_bounded_response_body(
                    response,
                    self.max_response_body_bytes,
                ).await?;
                if #success_status_guard {
                    Ok(bytes::Bytes::from(body_bytes))
                } else {
                    let raw_body = body_bytes;
                    let body_text = String::from_utf8_lossy(&raw_body).into_owned();
                    if status.is_success() {
                        return Err(ApiOpError::Api(ApiError {
                            status: status_code,
                            headers,
                            body: body_text,
                            raw_body,
                            typed: None,
                            parse_error: Some(format!(
                                "unexpected successful status {}; generated return type selects `{}`",
                                status_code,
                                #selected_status,
                            )),
                        }));
                    }
                    let typed: Option<#op_error_type>;
                    let parse_error: Option<String>;
                    #error_match_arms
                    Err(ApiOpError::Api(ApiError {
                        status: status_code,
                        headers,
                        body: body_text,
                        raw_body,
                        typed,
                        parse_error,
                    }))
                }
            };
        }

        quote! {
            let status = response.status();
            let status_code = status.as_u16();
            let headers = response.headers().clone();
            let body_bytes = __read_bounded_response_body(
                response,
                self.max_response_body_bytes,
            ).await?;
            let raw_body = body_bytes;
            let body_text = String::from_utf8_lossy(&raw_body).into_owned();

            if #success_status_guard {
                #success_branch
            } else if status.is_success() {
                Err(ApiOpError::Api(ApiError {
                    status: status_code,
                    headers,
                    body: body_text,
                    raw_body,
                    typed: None,
                    parse_error: Some(format!(
                        "unexpected successful status {}; generated return type selects `{}`",
                        status_code,
                        #selected_status,
                    )),
                }))
            } else {
                let typed: Option<#op_error_type>;
                let parse_error: Option<String>;
                #error_match_arms
                Err(ApiOpError::Api(ApiError {
                    status: status_code,
                    headers,
                    body: body_text,
                    raw_body,
                    typed,
                    parse_error,
                }))
            }
        }
    }

'''
text = replace_between(text, error_start, error_end, new_error)

path.write_text(text)

test = r'''use openapi_to_rust::client_generator::ClientResponseRepresentation;
use openapi_to_rust::{CodeGenerator, GeneratorConfig, SchemaAnalyzer};
use serde_json::json;
use std::path::PathBuf;

fn generator() -> CodeGenerator {
    CodeGenerator::new(GeneratorConfig {
        spec_path: PathBuf::from("fixture.json"),
        output_dir: PathBuf::from("target/response-call-shape-fixture"),
        module_name: "fixture".to_string(),
        enable_async_client: true,
        ..Default::default()
    })
}

#[test]
fn plans_multiple_response_call_shapes_without_using_rust_names_as_identity()
-> Result<(), Box<dyn std::error::Error>> {
    let spec = json!({
        "openapi": "3.1.0",
        "info": {"title": "Response Call Shapes", "version": "1.0.0"},
        "paths": {
            "/json-only": {
                "get": {
                    "operationId": "jsonOnly",
                    "responses": {
                        "200": {
                            "description": "json",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/RenderResult"}
                                }
                            }
                        }
                    }
                }
            },
            "/render": {
                "post": {
                    "operationId": "render",
                    "responses": {
                        "200": {
                            "description": "multiple representations",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/RenderResult"}
                                },
                                "audio/wav": {
                                    "schema": {"type": "string", "format": "binary"}
                                },
                                "text/event-stream": {
                                    "schema": {"type": "string"}
                                }
                            }
                        }
                    }
                }
            },
            "/reserved-stream-name": {
                "get": {
                    "operationId": "renderStream",
                    "responses": {
                        "200": {
                            "description": "reserve the preferred generated suffix",
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
        "components": {
            "schemas": {
                "RenderResult": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {"id": {"type": "string"}}
                }
            }
        }
    });

    let mut analyzer = SchemaAnalyzer::new(spec)?;
    let analysis = analyzer.analyze()?;
    let generator = generator();
    let plan = generator.plan_client_call_shapes(&analysis);

    let json_only: Vec<_> = plan
        .iter()
        .filter(|shape| shape.source_operation.operation_id == "jsonOnly")
        .collect();
    assert_eq!(json_only.len(), 1);
    assert!(matches!(
        json_only[0].representation,
        ClientResponseRepresentation::Json { .. }
    ));

    let render: Vec<_> = plan
        .iter()
        .filter(|shape| shape.source_operation.operation_id == "render")
        .collect();
    assert_eq!(render.len(), 4, "{render:#?}");

    let json = render
        .iter()
        .find(|shape| matches!(shape.representation, ClientResponseRepresentation::Json { .. }))
        .expect("buffered json call shape");
    assert_eq!(json.rust_method_name, "render");
    assert_eq!(json.success_type, "RenderResult");

    let wav = render
        .iter()
        .find(|shape| {
            matches!(
                &shape.representation,
                ClientResponseRepresentation::BinaryBuffered { media_type, .. }
                    if media_type == "audio/wav"
            )
        })
        .expect("buffered wav call shape");
    assert_eq!(wav.rust_method_name, "render_wav");
    assert_eq!(wav.success_type, "bytes::Bytes");

    let wav_stream = render
        .iter()
        .find(|shape| {
            matches!(
                &shape.representation,
                ClientResponseRepresentation::BinaryStream { media_type, .. }
                    if media_type == "audio/wav"
            )
        })
        .expect("live wav call shape");
    assert_eq!(wav_stream.rust_method_name, "render_wav_stream");
    assert_eq!(wav_stream.success_type, "HttpResponseByteStream");

    let sse = render
        .iter()
        .find(|shape| {
            matches!(
                &shape.representation,
                ClientResponseRepresentation::EventStream { media_type }
                    if media_type == "text/event-stream"
            )
        })
        .expect("SSE call shape");
    assert_eq!(
        sse.rust_method_name, "render_stream_2",
        "the real renderStream operation reserves render_stream, but transport identity survives"
    );
    assert_eq!(sse.source_operation.method, "POST");
    assert_eq!(sse.source_operation.path, "/render");

    let client = generator.generate_http_client(&analysis)?;
    for method in [
        "pub async fn render(",
        "pub async fn render_wav(",
        "pub async fn render_wav_stream(",
        "pub async fn render_stream_2(",
    ] {
        assert!(client.contains(method), "missing `{method}` in:\n{client}");
    }
    Ok(())
}
'''
Path("tests/client_response_call_shapes_test.rs").write_text(test)
