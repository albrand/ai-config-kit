async function updateRecord(): Promise<string> {
  return await Promise.resolve("updated");
}

await updateRecord();
