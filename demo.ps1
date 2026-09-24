# The live WhatsApp demo in one command (Windows):  .\demo.ps1         reads with DeepSeek
#                                                   .\demo.ps1 -Rules  reads with the regex rules
# Needs live.env filled in (copy live.env.example). See reach_agent/live.py for what it does.
param([switch]$Rules)
Set-Location $PSScriptRoot
if (-not $env:DEEPSEEK_API_KEY) {
    $env:DEEPSEEK_API_KEY = [Environment]::GetEnvironmentVariable("DEEPSEEK_API_KEY", "User")
}
$llm = if ($Rules) { @() } else { @("--llm", "deepseek") }
& "$PSScriptRoot\.venv\Scripts\python.exe" -m reach_agent.live @llm
