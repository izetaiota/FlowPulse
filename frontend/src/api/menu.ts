import client from "./client";

export interface MenuItemData {
  id: string;
  title: string;
  path: string;
  icon: string;
  parent: string;
  visible: boolean;
}

export const menuApi = {
  list: () =>
    client.get("/menus") as unknown as Promise<{ menus: MenuItemData[] }>,
  save: (menus: MenuItemData[]) =>
    client.put("/menus", { menus }) as unknown as Promise<{ menus: MenuItemData[] }>,
  reset: () =>
    client.post("/menus/reset") as unknown as Promise<{ menus: MenuItemData[] }>,
};
