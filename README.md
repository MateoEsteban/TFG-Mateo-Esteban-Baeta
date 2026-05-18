# Controlador SDN para la Gestión de Network Slices en Redes de Transporte 5G

Este repositorio contiene el código fuente y el entorno de emulación correspondientes al Trabajo de Fin de Grado: **"Diseño e implementación de un controlador para la gestión de rodajas de red en redes de transportes 5G"**. 

El proyecto implementa un orquestador SDN capaz de aprovisionar dinámicamente rodajas de red (Network Slices) aplicando control de admisión matemático, ingeniería de tráfico con Segment Routing (SRv6) y políticas de Calidad de Servicio (QoS) jerárquicas (modelo HCTNS) de forma totalmente automatizada (Zero-Touch Provisioning).

---

## Requisitos Previos

Para ejecutar este proyecto, necesitas un entorno Linux (preferiblemente Ubuntu) con las siguientes herramientas instaladas:

*   **VNX (Virtual Networks over LinuX):** Para la emulación de la topología de red.
*   **LXC (Linux Containers):** Subsistema de virtualización utilizado por VNX.
*   **Python 3.8+** con las siguientes librerías:
    ```bash
    pip install fastapi uvicorn networkx
    ```

---

## Despliegue del Escenario de Red

Antes de iniciar el controlador, es necesario levantar el "gemelo digital" o topología física emulada sobre la que operará el sistema.

Ejecuta el script de inicialización para construir y arrancar el escenario ACROSS virtualizado:
```bash
python3 startscenario.py
```
**Nota:** Este script invoca a VNX leyendo el archivo escenario-across-vnx.xml y levanta todos los contenedores LXC necesarios: rg, r1 a r7, ru, así como los nodos de acceso rgnb y rupf.

---

## ⚙️ Ejecución del Controlador SDN

Una vez que la red física está operativa, puedes levantar el Network Control Stack (Orquestador SDN).

Sitúate en el directorio donde se encuentra el código del controlador (`main.py`, `pce.py`, `src.py`) y lanza la API REST y el servidor web utilizando Uvicorn ejecutando el siguiente comando:
```bash
sudo python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
```
**Nota:** Es necesario ejecutarlo con privilegios sudo ya que el módulo src.py utiliza lxc-attach internamente para inyectar reglas de tráfico en los routers.

Verás en la terminal un mensaje indicando que la aplicación ha arrancado correctamente y está a la espera de peticiones.

---

## Uso de la Aplicación (Interfaz Web)

El controlador expone una interfaz gráfica amigable para el operador de red. Abre un navegador web y accede a: **http://localhost:8000**

### Despliegue de Network Slices

En la pantalla principal verás un panel para introducir los parámetros SLA de la nueva rodaja:

- **Burst (Bytes):** Tamaño de la micro-ráfaga permitida (por defecto 1500)
- **CIR (Mbps):** Ancho de banda garantizado para el flujo
- **Delay máximo (ms):** Retardo máximo tolerado. (Si es ≤ 5ms, el sistema lo catalogará como tráfico crítico URLLC; si es ≤ 20ms, como Vídeo, etc.)

Puedes añadir múltiples flujos a la misma Slice usando el botón "+ Añadir Clase" y haz clic en "Lanzar Petición".

### ¿Qué ocurre internamente?

- El Módulo PCE (pce.py) recibe la petición, calcula matemáticamente el overhead de las cabeceras SRv6 (factor 1.2), evalúa la topología en tiempo real y busca una ruta óptima.
- Si la red se saturaría, la petición es rechazada de inmediato para proteger la infraestructura (Error 406).
- Si hay recursos, la interfaz te mostrará en verde "¡Aceptado! Slice creada", indicándote la VLAN asignada y el camino elegido.
- El Módulo SRC (src.py) inyecta instantáneamente las reglas de encapsulación SRv6, marcado DSCP y las disciplinas de colas jerárquicas (HTB, DRR, PRIO) en los contenedores LXC.

### Desmantelamiento

En la parte inferior de la web verás una sección de "Slices Activas". Si haces clic en el botón "Eliminar", el controlador borrará automáticamente todas las reglas de los enrutadores y devolverá los megas de ancho de banda al balance de la red, dejándolos disponibles para futuras peticiones.

---
Autor: Mateo Esteban Baeta
Institución: Escuela Técnica Superior de Ingenieros de Telecomunicación (ETSIT - UPM)