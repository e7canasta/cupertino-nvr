# [TECH-DEBT] Event Persistence & Historical Storage

**Priority**: P1  
**Effort**: 3 story points  
**Epic**: Phase 2 - Scale & Performance  
**Labels**: persistence, storage, events  

## Problem Statement

Currently events are only stored in-memory with TTL-based cache. For production needs:
- Historical event analysis and reporting
- Audit trail for compliance requirements
- Event replay for debugging and testing
- Long-term metrics and trend analysis

## Acceptance Criteria

- [ ] Persistent event storage (database or time-series DB)
- [ ] Configurable retention policies (e.g., 30 days, 1 year)
- [ ] Event query API with filtering and pagination
- [ ] Historical metrics aggregation and rollups
- [ ] Event replay functionality for testing
- [ ] Performance: handle 1000+ events/second ingestion
- [ ] Storage optimization with compression/archival
- [ ] Backup and recovery procedures

## Technical Notes

**Storage Options:**
1. **Time-Series DB**: InfluxDB, TimescaleDB for metrics
2. **Document DB**: MongoDB, Elasticsearch for events
3. **Relational DB**: PostgreSQL with time partitioning
4. **Event Store**: EventStore, Apache Kafka for event sourcing

**Recommended Approach:**
- TimescaleDB for metrics (time-series optimization)
- PostgreSQL for events (JSON columns, ACID properties)
- Redis for hot cache (current TTL system)

**Schema Design:**
```sql
-- Events table
CREATE TABLE detection_events (
    id SERIAL PRIMARY KEY,
    source_id VARCHAR(50) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    event_data JSONB NOT NULL,
    frame_id BIGINT,
    detection_count INTEGER
);

-- Metrics table (TimescaleDB hypertable)
CREATE TABLE processor_metrics (
    time TIMESTAMPTZ NOT NULL,
    processor_id VARCHAR(50) NOT NULL,
    fps FLOAT,
    cpu_percent FLOAT,
    memory_mb INTEGER,
    detection_count INTEGER
);
```

## Migration Strategy

1. **Phase 1**: Add persistence layer alongside current cache
2. **Phase 2**: Implement query API and historical views
3. **Phase 3**: Add retention policies and cleanup jobs
4. **Phase 4**: Optimize performance and add advanced features

## Performance Considerations

- Batch inserts for high throughput
- Asynchronous writing to avoid blocking
- Proper indexing strategy
- Compression for older data
- Read replicas for query workloads

## Definition of Done

- [ ] Events persisted to database successfully
- [ ] Query API implemented with filtering
- [ ] Retention policies configured and tested
- [ ] Performance benchmarks meet requirements
- [ ] Migration from cache-only completed
- [ ] Monitoring and alerting for storage health
- [ ] Documentation updated with persistence layer