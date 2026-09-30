/** Substitutes the {name} placeholder of a quick-reply template. */
export function substituteQuickReply(body: string, name: string | null | undefined): string {
  const displayName = (name ?? "").trim();
  return body.split("{name}").join(displayName);
}
