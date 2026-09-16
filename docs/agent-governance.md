# Agent Governance Foundation

`core.agent_governance.AgentGovernance` is the single coordination facade for the existing executable-agent, specification, and version registries.

## Contract

An agent can be registered for runtime use only when:

- executable agent, `AgentSpec`, and `AgentVersion` names match;
- the specification and version share the same `AgentLifecycle`;
- that lifecycle is `ENABLED`;
- the version metadata validates successfully; and
- no duplicate executable agent, specification, or enabled version already exists.

The facade performs all expected validation before mutating its registries. It does not perform runtime routing, deployment, automatic mutation, or rollback.

## Next phase

Control Tower / AI Manager runtime wiring should consume this facade rather than coordinating the three registries independently. That integration remains a separate change so the governance foundation can be tested independently first.
