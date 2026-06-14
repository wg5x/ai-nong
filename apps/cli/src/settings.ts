import { homedir } from "node:os";
import { join } from "node:path";

export function ainongHome(): string {
  return process.env.AINONG_HOME || join(homedir(), ".ainong");
}

export function dreaminaCommand(): string {
  return process.env.DREAMINA_COMMAND || "dreamina";
}

export function dreaminaBaseDir(): string {
  return join(ainongHome(), "dreamina");
}

export function downloadDir(): string {
  return process.env.AINONG_DOWNLOAD_DIR || join(dreaminaBaseDir(), "downloads");
}

export function lockTtlSeconds(): number {
  return Number.parseInt(process.env.AINONG_LOCK_TTL_SECONDS || "1800", 10);
}
