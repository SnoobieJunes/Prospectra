# prospectra-jira

The reference Prospectra connector plugin. It registers a `JiraConnector` through the
`prospectra.connectors` entry-point group, and implements it by *describing* Jira's REST API as a
`RestMapping` rather than reimplementing HTTP — auth, pagination, and flattening all come from
Prospectra's REST tier.

```sh
uv add prospectra-jira      # in a real install
```

Then Jira appears in **Sources ▸ Add API…** with no change to Prospectra itself.

**Status: experimental.** No live Jira site has been called from this build — there are no
credentials here. Per Prospectra's honesty rule, the badge stays "experimental" until someone makes
a real call and observes it.

See `docs/writing-a-connector.md` in the main repo for how to write your own in under 100 lines.
