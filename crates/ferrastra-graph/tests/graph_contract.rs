//    Ferrastra - CPU-first native graphics product engine
//    Copyright (C) 2025  Artificial Sweetener and contributors
//
//    This program is free software: you can redistribute it and/or modify
//    it under the terms of the GNU General Public License as published by
//    the Free Software Foundation, either version 3 of the License, or
//    (at your option) any later version.
//
//    This program is distributed in the hope that it will be useful,
//    but WITHOUT ANY WARRANTY; without even the implied warranty of
//    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
//    GNU General Public License for more details.
//
//    You should have received a copy of the GNU General Public License
//    along with this program.  If not, see <https://www.gnu.org/licenses/>.

//! Contract proof for graph validation and cycle rejection.

use std::collections::BTreeMap;

use ferrastra_core::{
    AlphaMode, AuthoringDescriptor, CapabilitySet, ComputationDescriptor, ContentId, EdgeMode,
    ExposureClass, Locality, OperationCategory, OperationDescriptor, OperationIdentity,
    PortDescriptor, PortDirection, PortId, ProductSpec, QualityTier, RasterFormat,
    SemanticOperationId, SemanticVersion, SupportRadius, WorkingSpace,
};
use ferrastra_graph::{
    BuilderError, GraphAuthoring, GraphBuilder, GraphChange, GraphDefinition, GraphName,
    GraphPatch, GraphRecords, GraphRevisionId, GraphSchemaVersion, InputBinding, NodeAuthoring,
    NodeDefinition, NodeId, NodeOutput, ParameterBinding, PatchError, PatchPrecondition,
    UnknownRecord, apply_patch, compile_graph, deserialize_graph, serialize_graph, validate_graph,
};

mod construction {
    use super::*;

    #[test]
    fn duplicate_records_leave_the_first_definition_unchanged() {
        let mut builder = GraphBuilder::new(
            GraphSchemaVersion::new(1)
                .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
            GraphRevisionId::new(1)
                .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
        );
        let node = node_id(1);
        let first_operation = operation_identity("ferrastra.fixture.first");
        builder
            .add_node(node, first_operation.clone())
            .unwrap_or_else(|error| unreachable!("valid node rejected: {error}"));
        assert_eq!(
            builder.add_node(node, operation_identity("ferrastra.fixture.second")),
            Err(BuilderError::DuplicateNode)
        );
        let name = GraphName::new("result")
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));
        let first_output = NodeOutput { node, port: port_id("first") };
        builder
            .add_output(name.clone(), first_output.clone())
            .unwrap_or_else(|error| unreachable!("valid output rejected: {error}"));
        assert_eq!(
            builder.add_output(name.clone(), NodeOutput { node, port: port_id("second") }),
            Err(BuilderError::DuplicateOutput)
        );

        let graph = builder.build();
        assert_eq!(graph.nodes()[&node].operation, first_operation);
        assert_eq!(graph.outputs()[&name], first_output);
    }
}

mod validation {
    use super::*;

    #[test]
    fn valid_typed_source_to_identity_graph_is_accepted() {
        let (graph, catalog) = source_identity_graph(false);
        let report = validate_graph(&graph, &catalog, &CapabilitySet::default())
            .unwrap_or_else(|error| unreachable!("stable diagnostic rejected: {error}"));

        assert!(report.valid);
        assert!(report.diagnostics.is_empty());
    }

    #[test]
    fn cycle_rejection_is_sensitive_to_one_back_edge() {
        let (graph, catalog) = source_identity_graph(true);
        let report = validate_graph(&graph, &catalog, &CapabilitySet::default())
            .unwrap_or_else(|error| unreachable!("stable diagnostic rejected: {error}"));

        assert!(!report.valid);
        assert!(report.diagnostics.iter().any(|item| item.code.as_str() == "GRAPH_CYCLE"));
    }
}

mod patching {
    use super::*;

    #[test]
    fn exact_preconditions_publish_one_complete_next_revision() {
        let (graph, catalog) = source_identity_graph(false);
        let source_node = node_id(1);
        let revision = ContentId::from_bytes([3; ContentId::BYTE_LENGTH]);
        let patch = GraphPatch {
            base_revision: graph.revision_id(),
            next_revision: GraphRevisionId::new(2)
                .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
            preconditions: Box::new([PatchPrecondition::SourceRevision {
                node: source_node,
                expected: None,
            }]),
            changes: Box::new([GraphChange::ReplaceSourceRevision { node: source_node, revision }]),
        };

        let next = apply_patch(&graph, &patch, &catalog, &CapabilitySet::default())
            .unwrap_or_else(|error| unreachable!("valid patch rejected: {error}"));

        assert_eq!(graph.nodes()[&source_node].source_revision, None);
        assert_eq!(next.nodes()[&source_node].source_revision, Some(revision));
        assert_eq!(next.revision_id(), patch.next_revision);
        assert_ne!(next.content_id(), graph.content_id());
    }

    #[test]
    fn stale_or_invalid_patches_publish_nothing() {
        let (graph, catalog) = source_identity_graph(false);
        let stale = GraphPatch {
            base_revision: GraphRevisionId::new(9)
                .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
            next_revision: GraphRevisionId::new(10)
                .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
            preconditions: Box::default(),
            changes: Box::default(),
        };
        assert_eq!(
            apply_patch(&graph, &stale, &catalog, &CapabilitySet::default()),
            Err(PatchError::StaleBase)
        );

        let invalid = GraphPatch {
            base_revision: graph.revision_id(),
            next_revision: GraphRevisionId::new(2)
                .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
            preconditions: Box::default(),
            changes: Box::new([GraphChange::RemoveNode { node: node_id(1) }]),
        };
        assert!(matches!(
            apply_patch(&graph, &invalid, &catalog, &CapabilitySet::default()),
            Err(PatchError::Validation(_))
        ));
        assert_eq!(graph.nodes().len(), 2);
        assert_eq!(graph.revision_id().get(), 1);
    }
}

mod compilation {
    use super::*;

    #[test]
    fn compiled_plan_is_dependency_first_and_keeps_graph_identity() {
        let (graph, catalog) = source_identity_graph(false);
        let plan = compile_graph(&graph, &catalog, &CapabilitySet::default())
            .unwrap_or_else(|error| unreachable!("valid graph rejected: {error}"));

        assert_eq!(plan.graph_content_id(), graph.content_id());
        assert_eq!(
            plan.nodes().iter().map(|node| node.node).collect::<Vec<_>>(),
            vec![node_id(1), node_id(2)]
        );
        assert_eq!(plan.nodes()[1].dependencies.as_ref(), &[node_id(1)]);
    }
}

mod serialization {
    use super::*;

    const PHASE1_IDENTITY_GRAPH: &str = include_str!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../packages/ferrastra/tests/fixtures/phase1_identity_graph.json"
    ));

    #[test]
    fn canonical_json_round_trips_deterministically() {
        let (graph, _) = source_identity_graph(false);
        let first = serialize_graph(&graph)
            .unwrap_or_else(|error| unreachable!("valid graph rejected: {error}"));
        let restored = deserialize_graph(&first)
            .unwrap_or_else(|error| unreachable!("canonical graph rejected: {error}"));
        let second = serialize_graph(&restored)
            .unwrap_or_else(|error| unreachable!("restored graph rejected: {error}"));

        assert_eq!(restored, graph);
        assert_eq!(first, second);
    }

    #[test]
    fn serialized_content_identity_is_verified_before_adoption() {
        let (graph, _) = source_identity_graph(false);
        let serialized = serialize_graph(&graph)
            .unwrap_or_else(|error| unreachable!("valid graph rejected: {error}"));
        let mut record: serde_json::Value = serde_json::from_slice(&serialized)
            .unwrap_or_else(|error| unreachable!("canonical JSON rejected: {error}"));
        record["content_id"] = serde_json::Value::String("00".repeat(ContentId::BYTE_LENGTH));
        let tampered = serde_json::to_vec(&record)
            .unwrap_or_else(|error| unreachable!("test record rejected: {error}"));

        assert!(matches!(
            deserialize_graph(&tampered),
            Err(ferrastra_graph::GraphCodecError::ContentIdentityMismatch)
        ));
    }

    #[test]
    fn canonical_phase1_fixture_has_the_same_native_content_identity() {
        let graph = deserialize_graph(PHASE1_IDENTITY_GRAPH.as_bytes())
            .unwrap_or_else(|error| unreachable!("canonical graph rejected: {error}"));
        let serialized = serialize_graph(&graph)
            .unwrap_or_else(|error| unreachable!("canonical graph rejected: {error}"));

        assert_eq!(
            graph.content_id().to_string(),
            "81b201371878e651173c79a00a6b56b54ab680c35ee30cb756ac6b995cfcdf69"
        );
        assert_eq!(serialized.as_ref(), PHASE1_IDENTITY_GRAPH.trim().as_bytes());
    }
}

fn source_identity_graph(
    cyclic: bool,
) -> (GraphDefinition, BTreeMap<OperationIdentity, OperationDescriptor>) {
    let source_identity = operation_identity("ferrastra.source.raster");
    let pass_identity = operation_identity("ferrastra.core.identity");
    let source_descriptor = descriptor(source_identity.clone(), false);
    let pass_descriptor = descriptor(pass_identity.clone(), true);
    let source_id = node_id(1);
    let pass_id = node_id(2);
    let result_port = port_id("result");
    let source_input = if cyclic {
        BTreeMap::from([(
            port_id("source"),
            InputBinding::Node(NodeOutput { node: pass_id, port: result_port.clone() }),
        )])
    } else {
        BTreeMap::new()
    };
    let nodes = BTreeMap::from([
        (
            source_id,
            NodeDefinition {
                operation: if cyclic { pass_identity.clone() } else { source_identity.clone() },
                parameters: BTreeMap::<_, ParameterBinding>::new(),
                inputs: source_input,
                source_revision: None,
                unknown_records: Box::new([unknown_record("fixture.node", &[1, 2, 3])]),
                authoring: NodeAuthoring::default(),
            },
        ),
        (
            pass_id,
            NodeDefinition {
                operation: pass_identity.clone(),
                parameters: BTreeMap::new(),
                inputs: BTreeMap::from([(
                    port_id("source"),
                    InputBinding::Node(NodeOutput { node: source_id, port: result_port.clone() }),
                )]),
                source_revision: None,
                unknown_records: Box::default(),
                authoring: NodeAuthoring::default(),
            },
        ),
    ]);
    let graph = GraphDefinition::new(
        GraphSchemaVersion::new(1)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
        GraphRevisionId::new(1)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
        GraphRecords {
            nodes,
            outputs: BTreeMap::from([(
                GraphName::new("result")
                    .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
                NodeOutput { node: pass_id, port: result_port },
            )]),
            unknown_records: Box::new([unknown_record("fixture.graph", &[9, 8, 7])]),
            ..GraphRecords::default()
        },
        GraphAuthoring::default(),
    );
    let catalog =
        BTreeMap::from([(source_identity, source_descriptor), (pass_identity, pass_descriptor)]);
    (graph, catalog)
}

fn descriptor(identity: OperationIdentity, has_input: bool) -> OperationDescriptor {
    let product = ProductSpec::raster(RasterFormat::Rgba8PremultipliedEncoded);
    let mut ports = Vec::new();
    if has_input {
        ports.push(PortDescriptor {
            id: port_id("source"),
            direction: PortDirection::Input,
            product,
            required: true,
        });
    }
    ports.push(PortDescriptor {
        id: port_id("result"),
        direction: PortDirection::Output,
        product,
        required: true,
    });
    OperationDescriptor {
        identity,
        exposure: ExposureClass::PublicGraph,
        category: if has_input { OperationCategory::Point } else { OperationCategory::Generator },
        ports: ports.into_boxed_slice(),
        parameters: Box::default(),
        computation: ComputationDescriptor {
            formats: Box::new([ferrastra_core::ProductFormat::Raster(
                RasterFormat::Rgba8PremultipliedEncoded,
            )]),
            alpha_modes: Box::new([AlphaMode::Premultiplied]),
            working_spaces: Box::new([WorkingSpace::SrgbEncoded]),
            edge_modes: Box::new([EdgeMode::Clamp]),
            quality_tiers: Box::new([QualityTier::Exact]),
            locality: Locality::Local,
            support: SupportRadius::default(),
            required_capabilities: CapabilitySet::default(),
            deterministic: true,
            tile_equivalent: true,
        },
        authoring: AuthoringDescriptor {
            summary: "Fixture operation".into(),
            details: "Defines complete metadata for graph validation tests.".into(),
            use_cases: Box::default(),
            warnings: Box::default(),
        },
        serialization_version: 1,
    }
}

fn operation_identity(value: &str) -> OperationIdentity {
    OperationIdentity::new(
        SemanticOperationId::new(value)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
        SemanticVersion::new(1)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
    )
}

fn node_id(value: u64) -> NodeId {
    NodeId::new(value).unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
}

fn port_id(value: &str) -> PortId {
    PortId::new(value).unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
}

fn unknown_record(kind: &str, payload: &[u8]) -> UnknownRecord {
    UnknownRecord::new(kind, payload)
        .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
}
