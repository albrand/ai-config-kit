# Allure and runner recipes

Every result needs a `scenario_id` label and stable title. Playwright: add Allure Playwright reporter and label each test; attach screenshot on executed browser cases. Vitest/Jest: use the runner adapter and add label in test metadata. pytest: use `allure-pytest` and `allure.dynamic.label("scenario_id", id)`. xUnit/NUnit: use Allure .NET attributes/labels. JUnit: use adapter labels. Parse raw result JSON as evidence; never infer pass from report text.

Allure 3 config should define results directory, single-file HTML output, and grouping by sprint/feature/scenario. Pin the CLI in the application repo, generate report after tests, upload as CI artifact and link from work item. Keep Allure packages out of this dependency-free kit.
