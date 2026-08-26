# Personal data migration

Mouser stores user-specific data outside the source repository.

On Windows, the user data directory is:

    %APPDATA%\Mouser

For this G502 fork, a private migration package can include:

- config.json - app settings and button mappings.
- last_device.json - last detected device metadata.
- g502_backups/*.json - G502 onboard-profile backups created before unlock/restore operations.
- logs/* - optional troubleshooting logs.

Do not publish this data in a public repository. It can contain local Windows
paths, device identifiers, application names, and debug logs.

To restore on another Windows computer:

1. Quit Mouser completely.
2. Extract the private migration package.
3. Copy the extracted Mouser folder to %APPDATA%\Mouser.
4. Start Mouser again.
5. Connect the G502 mouse and verify the device page/mappings.

