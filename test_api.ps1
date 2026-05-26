$ErrorActionPreference = "Stop"

function Test-Endpoint {
    param($Name, $Url, $Method="GET", $Body=$null, $Headers=@{})
    Write-Host "Testing $Name..." -NoNewline
    try {
        $params = @{
            Uri = $Url
            Method = $Method
            Headers = $Headers
            ContentType = "application/json"
        }
        if ($Body) { $params.Body = $Body }
        if ($Method -eq "POST" -and $Url -match "login") {
            $params.ContentType = "application/x-www-form-urlencoded"
        }

        $response = Invoke-RestMethod @params
        Write-Host " OK" -ForegroundColor Green
        return $response
    } catch {
        Write-Host " FAILED" -ForegroundColor Red
        Write-Host $_.Exception.Message
        if ($_.Exception.Response) {
            $reader = New-Object System.IO.StreamReader $_.Exception.Response.GetResponseStream()
            Write-Host $reader.ReadToEnd()
        }
        return $null
    }
}

# 1. Health
Test-Endpoint "Health Check" "http://localhost:8000/health"

# 2. Login
$loginBody = "username=admin&password=admin123"
$tokenResponse = Test-Endpoint "Login" "http://localhost:8000/api/v1/login/access-token" "POST" $loginBody
if (-not $tokenResponse) { exit 1 }

$token = $tokenResponse.access_token
$authHeader = @{ "Authorization" = "Bearer $token" }
Write-Host "Token obtained."

# 3. Search Activos (Nuevo Endpoint)
$searchBody = @{ q = "NB" } | ConvertTo-Json
$activos = Test-Endpoint "Search Activos" "http://localhost:8000/api/v1/core/activos/search" "POST" $searchBody $authHeader

if ($activos -and $activos.Count -gt 0) {
    $activoId = $activos[0].ACT_Activo
    Write-Host "Found Activo ID: $activoId"

    # 4. Get Detail (Nuevo Endpoint)
    Test-Endpoint "Get Activo Detail" "http://localhost:8000/api/v1/core/activos/$activoId" "GET" $null $authHeader

    # 5. Test Trazabilidad (Listar Movimientos)
    Test-Endpoint "List Movimientos" "http://localhost:8000/api/v1/trazabilidad/movimientos" "GET" $null $authHeader
} else {
    Write-Host "No assets found to test detail endpoint." -ForegroundColor Yellow
}
