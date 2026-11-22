import { assertSafeTarget } from "./target-guard";
import { demoLoginPassword } from "./demo-logins";

assertSafeTarget(databaseUrl);
await prisma.user.update({ data: { password: demoLoginPassword } });
