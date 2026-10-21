# LLM output evidence

Use this reference when implementing or reviewing an existing path that consumes LLM output. Keep these evidence levels distinct:

1. **Execution:** the owned call path ran against the stated input and produced a captured result.
2. **Structure:** the result conforms to the required schema and types.
3. **Semantics:** content matches independently established expectations for the input.
4. **Usefulness:** the result is relevant and actionable for the beneficiary's task.
5. **Downstream consumption:** the actual consumer accepts and uses it as intended.
6. **Observable value:** the resulting user or operational outcome is evidenced at the owning boundary.

Evidence at one level does not imply the next. Build a representative offline replay with explicit inputs, captured responses, and expectations established independently of the output being judged. Include realistic boundaries and fault cases. An empty result is correct only when the input or requirement explicitly expects none; unexpected empty, irrelevant, fabricated, or disconnected output is a potential failure. Exercise the real downstream consumer where feasible. No live model, provider call, or billing is required merely to apply these skill contracts.
