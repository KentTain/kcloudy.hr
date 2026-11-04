import type { ModuleDescriptor } from "@/framework/module/types";

import { hrRoutes } from "./router";

export const hrModule: ModuleDescriptor = {
  name: "hr",
  version: "0.1.0",
  getRoutes: () => hrRoutes,
  icon: "users",
};

export default hrModule;
