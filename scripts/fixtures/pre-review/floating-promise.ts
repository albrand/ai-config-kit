async function continueHop(): Promise<void> {
  await Promise.resolve("continued");
}

void continueHop();
