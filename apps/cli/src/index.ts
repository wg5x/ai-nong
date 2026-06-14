#!/usr/bin/env node
import { Command } from "commander";
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const VERSION = "0.1.0";

function ainongHome(): string {
  return process.env.AINONG_HOME || join(homedir(), ".ainong");
}

function apiBaseUrl(): string {
  return process.env.AINONG_API_URL || "http://127.0.0.1:8765";
}

function ensureHome(): void {
  mkdirSync(ainongHome(), { recursive: true });
}

function commandExists(command: string): boolean {
  const result = spawnSync("sh", ["-lc", `command -v ${command}`], {
    encoding: "utf8",
  });
  return result.status === 0;
}

function runPassthrough(command: string, args: string[], env?: NodeJS.ProcessEnv): number {
  const result = spawnSync(command, args, {
    stdio: "inherit",
    env: { ...process.env, ...env },
  });
  return result.status ?? 1;
}

async function requestJson(path: string, init?: RequestInit): Promise<unknown> {
  const url = `${apiBaseUrl()}${path}`;
  const response = await fetch(url, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers || {}),
    },
  });
  const text = await response.text();
  const body = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : response.statusText;
    throw new Error(`${response.status} ${detail}`);
  }
  return body;
}

function printJson(value: unknown): void {
  console.log(JSON.stringify(value, null, 2));
}

const program = new Command();

program
  .name("ainong")
  .description("Dreamina-compatible CLI wrapper with account-pool support.")
  .version(VERSION);

program
  .command("doctor")
  .description("Check local ainong and dreamina prerequisites.")
  .action(() => {
    ensureHome();
    const checks = {
      ainongHome: ainongHome(),
      apiBaseUrl: apiBaseUrl(),
      dreaminaFound: commandExists("dreamina"),
      node: process.version,
    };
    printJson(checks);
    if (!checks.dreaminaFound) {
      console.error("dreamina not found. Install it with: curl -fsSL https://jimeng.jianying.com/cli | bash");
      process.exitCode = 1;
    }
  });

const accountsCommand = program
  .command("accounts")
  .description("List Dreamina accounts known by the local account pool.")
  .action(async () => {
    const result = await requestJson("/v1/dreamina/accounts");
    printJson(result);
  });

accountsCommand
  .command("refresh")
  .description("Refresh one Dreamina account credit snapshot.")
  .argument("<account_id>")
  .action(async (accountId: string) => {
    const result = await requestJson(`/v1/dreamina/accounts/${encodeURIComponent(accountId)}/refresh`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    printJson(result);
  });

accountsCommand
  .command("set-status")
  .description("Enable or disable one Dreamina account.")
  .argument("<account_id>")
  .argument("<status>", "active or disabled")
  .action(async (accountId: string, status: string) => {
    const result = await requestJson(`/v1/dreamina/accounts/${encodeURIComponent(accountId)}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    });
    printJson(result);
  });

const loginCommand = program
  .command("login")
  .description("Start or complete Dreamina login through the account-pool service.")
  .option("--local", "Run the official dreamina login directly without account-pool registration")
  .allowUnknownOption(true)
  .allowExcessArguments(true)
  .action(async (options: { local?: boolean }, command: Command) => {
    if (options.local) {
      process.exitCode = runPassthrough("dreamina", ["login", ...command.args]);
      return;
    }
    const result = await requestJson("/v1/dreamina/login", {
      method: "POST",
      body: JSON.stringify({}),
    });
    printJson(result);
  });

loginCommand
  .command("check")
  .description("Check a Dreamina login session and register it into the account pool when authorized.")
  .argument("<session_id>")
  .action(async (sessionId: string) => {
    const result = await requestJson(`/v1/dreamina/login/${encodeURIComponent(sessionId)}/check`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    printJson(result);
  });

program
  .command("status")
  .description("Query a Dreamina task status through the account pool.")
  .argument("<task_id>")
  .action(async (taskId: string) => {
    const result = await requestJson(`/v1/dreamina/tasks/${encodeURIComponent(taskId)}`);
    printJson(result);
  });

function addDreaminaPassthrough(name: string, dreaminaCommand: string): void {
  program
    .command(name)
    .description(`Submit ${dreaminaCommand} through the account-pool service.`)
    .allowUnknownOption(true)
    .allowExcessArguments(true)
    .action(async (_options: unknown, command: Command) => {
      const result = await requestJson("/v1/dreamina/tasks", {
        method: "POST",
        body: JSON.stringify({
          command: dreaminaCommand,
          args: command.args,
        }),
      });
      printJson(result);
    });
}

addDreaminaPassthrough("text2video", "text2video");
addDreaminaPassthrough("image2video", "image2video");
addDreaminaPassthrough("frames2video", "frames2video");

program
  .command("export")
  .description("Export a task package. Placeholder until package builder lands.")
  .argument("<task_id>")
  .option("--format <format>", "export format", "zip")
  .action((taskId: string, options: { format: string }) => {
    console.log(`export is not implemented yet: task=${taskId} format=${options.format}`);
    process.exitCode = 2;
  });

program
  .command("check")
  .description("Check a package. Placeholder until package checker lands.")
  .argument("<package_path>")
  .action((packagePath: string) => {
    if (!existsSync(packagePath)) {
      console.error(`package not found: ${packagePath}`);
      process.exitCode = 1;
      return;
    }
    console.log(`package check is not implemented yet: ${packagePath}`);
  });

function normalizedArgv(): string[] {
  const [node, script, ...args] = process.argv;
  const normalizedArgs = args[0] === "--" ? args.slice(1) : args;
  return [node, script, ...normalizedArgs];
}

program.parseAsync(normalizedArgv()).catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
