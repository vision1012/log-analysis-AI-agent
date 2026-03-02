# Knowledge Graph Ontology — Design Documentation

## Overview

This document defines the ontology for the Neo4j-based Knowledge Graph that extends the autonomous debugging system. The ontology describes the domain concepts, entity types, and semantic structure used to represent log analysis, debugging workflows, and incident knowledge.

## Scope

The ontology covers:

- **Log entities**: Log sources, templates, events, and structured log entries
- **Debugging artifacts**: Jobs, runs, anomalies, and investigation outputs
- **Temporal context**: Timestamps, windows, and event ordering
- **Semantic relationships**: To be defined in a later phase (see `models.md` for node definitions only)

## Design Principles

- **Minimal coupling**: The graph layer does not modify existing V1 modules (api, agent, utilities, machine_learning)
- **Extensibility**: Node types and properties are designed for future relationship modeling
- **Temporal awareness**: All time-sensitive entities support temporal modeling (see `time_model.md`)

## Domain Concepts

| Concept | Description |
|---------|-------------|
| LogSource | Origin of log data (file, stream, system) |
| LogTemplate | Parsed log template / pattern |
| LogEvent | Individual log line or structured event |
| Anomaly | Detected anomaly from ML or heuristics |
| Job | Debugging job / analysis run |
| Investigation | Investigation step or finding |

## Versioning

- **Version**: 1.0
- **Status**: Design phase — node definitions and constraints only; relationships deferred
