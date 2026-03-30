// Reference: minimal graph for anomaly_001 (same as scripts/seed_demo_anomaly.py).
// file_id for demo/repo + src/handlers/checkout_handler.py (matches graph.writer._compute_file_id):
// 94f54d4e173015a83f2d5788c58b8898

MERGE (a:Anomaly {id: 'anomaly_001'})
SET a.timestamp = '2025-03-01T12:00:00+00:00',
    a.trace_ref = 'trace_demo_001',
    a.service_ref = 'demo-checkout-service',
    a.score = 0.85,
    a.severity = 'high',
    a.message = 'Demo: payment failure in checkout handler';

MERGE (s:StackFrame {id: 'sf_demo_anomaly_001_0'})
SET s.trace_ref = 'trace_demo_001',
    s.symbol_name = 'processPayment',
    s.resolution = 'resolved';

MERGE (f:File {file_id: '94f54d4e173015a83f2d5788c58b8898'})
SET f.path = 'src/handlers/checkout_handler.py',
    f.repo_ref = 'demo/repo';

MATCH (a:Anomaly {id: 'anomaly_001'}), (s:StackFrame {id: 'sf_demo_anomaly_001_0'})
MERGE (a)-[r:HAS_FRAME]->(s)
SET r.frame_order = 0;

MATCH (s:StackFrame {id: 'sf_demo_anomaly_001_0'}), (f:File {file_id: '94f54d4e173015a83f2d5788c58b8898'})
MERGE (s)-[:IN_FILE]->(f);

MERGE (c:Commit {sha: 'deadbeef0000000000000000000000000000abcd', repo_ref: 'demo/repo'})
SET c.timestamp = '2025-03-01T10:30:00+00:00';

MATCH (c:Commit {sha: 'deadbeef0000000000000000000000000000abcd', repo_ref: 'demo/repo'}),
      (f:File {file_id: '94f54d4e173015a83f2d5788c58b8898'})
MERGE (c)-[:TOUCHED]->(f);

MERGE (d:Deployment {id: 'dep_demo_001'})
SET d.timestamp = '1740000000',
    d.service_ref = 'demo-checkout-service';

MATCH (d:Deployment {id: 'dep_demo_001'}),
      (c:Commit {sha: 'deadbeef0000000000000000000000000000abcd', repo_ref: 'demo/repo'})
MERGE (d)-[:DEPLOYED_COMMIT]->(c);
