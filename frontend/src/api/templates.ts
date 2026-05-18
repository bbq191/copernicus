import client from "./client";

export interface TemplateInfo {
  id: string;
  name: string;
  description: string;
}

export async function listTemplates(): Promise<TemplateInfo[]> {
  const { data } = await client.get<TemplateInfo[]>("/templates");
  return data;
}
