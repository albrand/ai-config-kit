import { demoLoginPassword } from "./demo-logins";

await prisma.user.update({ data: { password: demoLoginPassword } });
