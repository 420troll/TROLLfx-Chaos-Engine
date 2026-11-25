# Run in Windows PowerShell after manually entering BOOTSEL. This script is read-only.
$ErrorActionPreference = 'Continue'
Write-Output '=== Present USB and port devices ==='
Get-PnpDevice -PresentOnly |
  Where-Object { $_.Class -in @('USB', 'USBDevice', 'Ports') -or $_.FriendlyName -match 'RP2|Pico|Spell|USB Serial|COM[0-9]+' } |
  Select-Object Class, FriendlyName, InstanceId, Status | Format-Table -AutoSize
Write-Output '=== Serial ports ==='
Get-CimInstance Win32_SerialPort |
  Select-Object DeviceID, Name, PNPDeviceID | Format-Table -AutoSize
Write-Output '=== Removable volumes / BOOTSEL drives ==='
Get-Volume | Where-Object { $_.DriveLetter -or $_.DriveType -eq 'Removable' } |
  Select-Object DriveLetter, FileSystemLabel, FileSystem, DriveType, Size, SizeRemaining | Format-Table -AutoSize
Write-Output '=== usbipd ==='
if (Get-Command usbipd -ErrorAction SilentlyContinue) { usbipd list } else { Write-Output 'usbipd-win is not installed or not on PATH' }
