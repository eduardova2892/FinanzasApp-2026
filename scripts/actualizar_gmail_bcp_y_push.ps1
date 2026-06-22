$ErrorActionPreference = "Stop"

$PROJECT = "C:\Users\eduar\OneDrive\Documents\01_EduPC_Legion\04 AppMyFinances"
$PYTHON = "$PROJECT\venv\Scripts\python.exe"

Set-Location $PROJECT

Write-Host "Actualizando bandeja Gmail BCP..."
& $PYTHON "$PROJECT\scripts\actualizar_gmail_bcp.py"

Write-Host "Preparando Git..."
git add data\bank_gmail_expenses_pending.csv
git add scripts\actualizar_gmail_bcp.py
git add scripts\actualizar_gmail_bcp_y_push.ps1

git diff --cached --quiet

if ($LASTEXITCODE -eq 1) {
    git commit -m "data: actualizar bandeja Gmail bancaria automática"
    git push
    Write-Host "Push completado."
}
else {
    Write-Host "No hay cambios nuevos para subir."
}
