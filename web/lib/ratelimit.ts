// Server-only wrapper around ratelimit-core. Pins the config store path and
// exposes the helpers /v1/* routes actually call.
import "server-only";
import path from "node:path";
import {
  checkAndConsume,
  getConfigAt,
  setConfigAt,
  snapshot,
  type Decision,
  type WorkspaceConfig,
  type Limits,
} from "./ratelimit-core";

export type { Decision, WorkspaceConfig, Limits } from "./ratelimit-core";
export { PLAN_DEFAULTS, defaultLimitsFor, defaultConfig } from "./ratelimit-core";

const ROOT =
  process.env.SHOTCLASSIFY_STORE_DIR ||
  path.join(process.cwd(), "..", "storage");
const STORE_PATH =
  process.env.SHOTCLASSIFY_RATELIMIT_FILE ||
  path.join(ROOT, "rate_limits.json");

export function ratelimitStorePath(): string {
  return STORE_PATH;
}

export function getWorkspaceConfig(workspaceId: string): Promise<WorkspaceConfig> {
  return getConfigAt(STORE_PATH, workspaceId);
}

export function setWorkspaceConfig(
  workspaceId: string,
  patch: Partial<{ plan: WorkspaceConfig["plan"]; limits: Partial<Limits> }>,
): Promise<WorkspaceConfig> {
  return setConfigAt(STORE_PATH, workspaceId, patch);
}

export async function enforce(workspaceId: string, keyId: string): Promise<Decision> {
  const cfg = await getWorkspaceConfig(workspaceId);
  return checkAndConsume({ workspaceId, keyId, config: cfg });
}

export function snapshotFor(workspaceId: string, keyId: string) {
  return snapshot(workspaceId, keyId);
}
