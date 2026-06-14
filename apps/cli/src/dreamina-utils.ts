export function parseLoginOutput(stdout: string): Record<string, string> {
  const fields: Record<string, string> = {};
  for (const key of ["verification_uri", "user_code", "device_code", "poll_interval", "expires_at"]) {
    const match = stdout.match(new RegExp(`^${key}:\\s*(.+?)\\s*$`, "m"));
    if (match?.[1]) {
      fields[key] = match[1].trim();
    }
  }
  if (!fields.verification_uri || !fields.device_code) {
    throw new Error("未能解析 dreamina 登录授权信息");
  }
  return fields;
}

export function parseJsonPayload(stdout: string): Record<string, unknown> | null {
  const text = stdout.trim();
  if (!text) {
    return null;
  }
  try {
    const parsed = JSON.parse(text);
    return isRecord(parsed) ? parsed : null;
  } catch {
    // Continue with embedded JSON extraction.
  }

  for (const candidate of extractJsonCandidates(text).reverse()) {
    try {
      const parsed = JSON.parse(candidate);
      if (isRecord(parsed)) {
        return parsed;
      }
    } catch {
      // Try the next candidate.
    }
  }
  return null;
}

export function providerUserIdFromCredit(credit: Record<string, unknown> | null): string {
  if (!credit) {
    return "";
  }
  for (const key of ["user_id", "uid", "userId"]) {
    const value = credit[key];
    if (value !== undefined && value !== null && String(value).trim()) {
      return String(value).trim();
    }
  }
  const user = credit.user;
  if (isRecord(user)) {
    for (const key of ["id", "user_id", "uid"]) {
      const value = user[key];
      if (value !== undefined && value !== null && String(value).trim()) {
        return String(value).trim();
      }
    }
  }
  return "";
}

export function accountIdFromProviderUserId(providerUserId: string, fallback: string): string {
  return /^[A-Za-z0-9_-]{3,64}$/.test(providerUserId) ? providerUserId : fallback;
}

export function extractSubmitId(stdout: string): string | null {
  const parsed = parseJsonPayload(stdout);
  const found = findSubmitId(parsed);
  if (found) {
    return found;
  }
  for (const pattern of [
    /"submit_id"\s*:\s*"([^"]+)"/i,
    /"submitId"\s*:\s*"([^"]+)"/i,
    /\bsubmit_id\b\s*[:=]\s*([A-Za-z0-9_-]+)/i,
    /\bsubmitId\b\s*[:=]\s*([A-Za-z0-9_-]+)/i,
  ]) {
    const match = stdout.match(pattern);
    if (match?.[1]) {
      return match[1];
    }
  }
  return null;
}

export function normalizeDreaminaStatus(status: unknown): string {
  const text = String(status || "").toLowerCase();
  if (text === "success" || text === "succeeded") {
    return "succeeded";
  }
  if (text === "fail" || text === "failed") {
    return "failed";
  }
  return "processing";
}

export function findVideoUrl(parsed: Record<string, unknown> | null): string | null {
  if (!parsed) {
    return null;
  }
  for (const container of [parsed.result_json, parsed]) {
    if (!isRecord(container)) {
      continue;
    }
    const videos = container.videos;
    if (Array.isArray(videos) && videos.length > 0 && isRecord(videos[0])) {
      const video = videos[0];
      const value = video.url || video.video_url || video.path;
      return value ? String(value) : null;
    }
  }
  return parsed.video_url ? String(parsed.video_url) : null;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function findSubmitId(value: unknown): string | null {
  if (!isRecord(value)) {
    return null;
  }
  for (const key of ["submit_id", "submitId"]) {
    const item = value[key];
    if (typeof item === "string") {
      return item;
    }
  }
  for (const child of Object.values(value)) {
    const found = findSubmitId(child);
    if (found) {
      return found;
    }
  }
  return null;
}

function extractJsonCandidates(text: string): string[] {
  const candidates: string[] = [];
  let start = -1;
  let depth = 0;
  let inString = false;
  let escaped = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (inString) {
      if (escaped) {
        escaped = false;
      } else if (char === "\\") {
        escaped = true;
      } else if (char === '"') {
        inString = false;
      }
      continue;
    }
    if (char === '"') {
      inString = true;
    } else if (char === "{") {
      if (depth === 0) {
        start = index;
      }
      depth += 1;
    } else if (char === "}" && depth > 0) {
      depth -= 1;
      if (depth === 0 && start >= 0) {
        candidates.push(text.slice(start, index + 1));
        start = -1;
      }
    }
  }
  return candidates;
}
