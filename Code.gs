/**
 * Code.gs — Google Apps Script para Gestión de Camiones
 * v5 — Always 10-column mapping (ignores extra columns)
 */

var API_TOKEN = "pablo9090";

var SPREADSHEET_ID = "1g9nAeqyimh5VMwkfane8kPstHedFIHKDE0C7HL5KhFw";
var SHEET_NAME = "Hoja1";

function doGet(e) {
  return handleRequest(e, 'get');
}

function doPost(e) {
  return handleRequest(e, 'post');
}

function handleRequest(e, method) {
  try {
    var token = method === 'get' ? e.parameter.token : JSON.parse(e.postData.contents).token;
    if (token !== API_TOKEN) {
      return respondJson({ success: false, error: "Token inválido" }, 403);
    }

    var action = method === 'get' ? e.parameter.action : JSON.parse(e.postData.contents).action;
    if (!action) {
      return respondJson({ success: false, error: "Parámetro 'action' requerido" }, 400);
    }

    var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    var sheet = ss.getSheetByName(SHEET_NAME);
    if (!sheet) sheet = ss.getSheets()[0];

    var result;
    switch (action) {
      case 'getAll':
        result = actionGetAll(sheet);
        break;
      case 'getRow':
        var fila = method === 'get' ? parseInt(e.parameter.fila) : JSON.parse(e.postData.contents).fila;
        result = actionGetRow(sheet, fila);
        break;
      case 'append':
        result = actionAppend(sheet, JSON.parse(e.postData.contents).values);
        break;
      case 'update':
        var d = JSON.parse(e.postData.contents);
        result = actionUpdate(sheet, d.fila, d.values);
        break;
      case 'clear':
        result = actionClear(sheet);
        break;
      case 'writeHeaders':
        result = actionWriteHeaders(sheet, JSON.parse(e.postData.contents).headers);
        break;
      case 'setAll':
        var d2 = JSON.parse(e.postData.contents);
        result = actionSetAll(sheet, d2.headers, d2.data);
        break;
      case 'deleteRow':
        var d3 = JSON.parse(e.postData.contents);
        result = actionDeleteRow(sheet, d3.fila);
        break;
      default:
        return respondJson({ success: false, error: "Acción desconocida: " + action }, 400);
    }

    return respondJson({ success: true, data: result });

  } catch (err) {
    return respondJson({ success: false, error: err.toString() }, 500);
  }
}

// ── ACCIONES ────────────────────────────────────────────────────

function actionGetAll(sheet) {
  var range = sheet.getDataRange();
  var rows = range.getValues();
  if (rows.length < 1) return [];
  var result = [];
  for (var i = 1; i < rows.length; i++) {
    var row = rows[i];
    if (!row.some(function(cell) { return cell !== "" && cell !== null; })) continue;
    result.push({
      fila_id: i + 1,
      nro: String(row[0] || ""),
      placa: String(row[1] || ""),
      estado_trabajo: String(row[2] || "Fijo"),
      tipo_combustible: String(row[3] || "GAS-GASOLINA"),
      costo_flete: parseFloat(row[4]) || 0,
      sucursal: String(row[5] || ""),
      capacidad_kg: parseInt(row[6]) || 0,
      capacidad_maples: parseInt(row[7]) || 0,
      capacidad_util_kg: parseFloat(row[8]) || 0,
      sistema_camion: String(row[9] || ""),
    });
  }
  return result;
}

function actionGetRow(sheet, fila) {
  if (fila < 1) throw new Error("fila debe ser >= 1");
  var numCols = Math.max(sheet.getLastColumn(), 10);
  var row = sheet.getRange(fila, 1, 1, numCols).getValues()[0];
  if (!row || row.length === 0) throw new Error("Fila " + fila + " no encontrada");
  return {
    fila_id: fila,
    nro: String(row[0] || ""),
    placa: String(row[1] || ""),
    estado_trabajo: String(row[2] || "Fijo"),
    tipo_combustible: String(row[3] || "GAS-GASOLINA"),
    costo_flete: parseFloat(row[4]) || 0,
    sucursal: String(row[5] || ""),
    capacidad_kg: parseInt(row[6]) || 0,
    capacidad_maples: parseInt(row[7]) || 0,
    capacidad_util_kg: parseFloat(row[8]) || 0,
    sistema_camion: String(row[9] || ""),
  };
}

function actionAppend(sheet, values) {
  if (!values || values.length < 10) throw new Error("Se requieren 10 valores");
  var flatValues = values.map(function(v) { return v !== null && v !== undefined ? v : ""; });
  sheet.appendRow(flatValues);
  return { fila_insertada: sheet.getLastRow(), valores: flatValues };
}

function actionUpdate(sheet, fila, values) {
  if (!fila || fila < 2) throw new Error("fila debe ser >= 2");
  if (!values || values.length < 10) throw new Error("Se requieren 10 valores");
  var flatValues = values.map(function(v) { return v !== null && v !== undefined ? v : ""; });
  var numCols = values.length;
  sheet.getRange(fila, 1, 1, numCols).setValues([flatValues]);
  return { fila_actualizada: fila, valores: flatValues };
}

function actionClear(sheet) {
  var lastRow = sheet.getLastRow();
  if (lastRow > 1) {
    sheet.getRange(2, 1, lastRow - 1, sheet.getLastColumn()).clearContent();
  }
  return { filas_limpiadas: lastRow - 1 };
}

function actionWriteHeaders(sheet, headers) {
  if (!headers || headers.length < 10) throw new Error("Se requieren 10 cabeceras");
  var numCols = headers.length;
  sheet.getRange(1, 1, 1, numCols).setValues([headers]);
  return { cabeceras_escritas: headers };
}

function actionSetAll(sheet, headers, data) {
  if (!headers || headers.length < 10) throw new Error("Se requieren 10 cabeceras");
  if (!data || !data.length) throw new Error("data vacío");
  var numCols = headers.length;
  var allRows = [headers];
  for (var i = 0; i < data.length; i++) {
    var row = data[i];
    var flat = [];
    for (var j = 0; j < numCols; j++) {
      flat.push(j < row.length ? (row[j] !== null && row[j] !== undefined ? row[j] : "") : "");
    }
    allRows.push(flat);
  }
  sheet.getRange(1, 1, allRows.length, numCols).setValues(allRows);
  return { filas_escritas: data.length };
}

function actionDeleteRow(sheet, fila) {
  if (!fila || fila < 2) throw new Error("fila debe ser >= 2");
  sheet.deleteRow(fila);
  return { fila_eliminada: fila };
}

function respondJson(data, statusCode) {
  var output = ContentService.createTextOutput(JSON.stringify(data));
  output.setMimeType(ContentService.MimeType.JSON);
  return output;
}
