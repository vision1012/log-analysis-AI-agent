"""
Neo4j constraints for Job nodes.

Run once per database (or at deploy) after the driver is configured.
"""

from __future__ import annotations

from typing import Optional

from neo4j import Driver

from db.neo4j.connection import get_driver

CONSTRAINT_JOB_ID_UNIQUE = """
CREATE CONSTRAINT job_id_unique IF NOT EXISTS
FOR (j:Job) REQUIRE j.job_id IS UNIQUE;
"""


def ensure_job_constraints(driver: Optional[Driver] = None) -> None:
    """
    Ensure ``Job.job_id`` uniqueness constraint exists.

    Args:
        driver: Optional driver; defaults to :func:`db.neo4j.connection.get_driver`.
    """
    drv = driver or get_driver()
    with drv.session() as session:
        session.run(CONSTRAINT_JOB_ID_UNIQUE)
