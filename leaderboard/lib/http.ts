import { NextResponse } from "next/server";

export const ok = (body: unknown = {}, status = 200) => NextResponse.json(body, { status });
export const fail = (error: string, status = 400) => NextResponse.json({ error }, { status });

/** Parses a JSON body, rejecting anything over maxBytes. */
export async function readJson(req: Request, maxBytes: number): Promise<unknown> {
  const text = await req.text();
  if (Buffer.byteLength(text) > maxBytes) throw new BodyError("payload too large", 413);
  try {
    return JSON.parse(text);
  } catch {
    throw new BodyError("invalid JSON", 400);
  }
}

export class BodyError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}
