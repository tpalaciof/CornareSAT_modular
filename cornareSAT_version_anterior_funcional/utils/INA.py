from adafruit_ina219 import INA219
from busio import I2C
from board import SCL, SDA

def measure_energy():

    # Inicializa el bus I²C
    i2c_bus = I2C(SCL, SDA)

    # Configura el INA219 para el panel solar (Dirección 0x40)
    panel_solar = INA219(i2c_bus,0x41)

    # Configura el INA219 para la batería (Dirección 0x41)
    bateria = INA219(i2c_bus,0x40)

    # Lee mediciones del panel solar
    voltaje_panel = panel_solar.bus_voltage + panel_solar.shunt_voltage  # Voltaje en V
    corriente_panel = panel_solar.current  # Corriente en mA

    # Lee mediciones de la batería
    voltaje_bateria = bateria.bus_voltage + bateria.shunt_voltage  # Voltaje en V
    corriente_bateria = bateria.current  # Corriente en mA

    return voltaje_bateria, corriente_bateria, voltaje_panel, corriente_panel

    # Imprime resultados

#v_bat, c_bat, v_panel, c_panel = measure_energy()
#print(v_bat)