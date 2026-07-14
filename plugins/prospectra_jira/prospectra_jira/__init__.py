# 2026-07-14 (P6): Jira connector plugin for Prospectra — the reference implementation of the
# `prospectra.connectors` entry-point API. See docs/writing-a-connector.md.
from prospectra_jira.connector import JiraConnector, jira_mapping

__all__ = ["JiraConnector", "jira_mapping"]
