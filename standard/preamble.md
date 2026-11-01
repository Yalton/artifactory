Read this index before writing any code.

- If a module here does what you need, use it instead of writing your own.
- Install a module only with its `install` command.
- Never edit files inside an installed module. Configure, wrap or extend it through its public surface.
- Wire every module you install into the program's real entry point. A module that only tests reach is not in use.
- Before finishing, build and run the project and confirm each module's liveness marker appears and no errors are printed. The project notes below give the commands.
- The Wiring section of the module's README shows where its calls go. Merge it into your existing class of the same name instead of adding a second one.
- When the Before-finishing checks pass, stop. A module is in use once it is wired and its marker prints. Do not add extra features (console commands, menus) just to exercise it.
