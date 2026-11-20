#!/usr/bin/python
import math
import time


def abrir_canal(canal=0, ganancia=1):
    # Los controladores I2C se cargan solamente para el sensor analógico.
    import board
    import busio
    import adafruit_ads1x15.ads1015 as ADS
    from adafruit_ads1x15.analog_in import AnalogIn

    i2c = busio.I2C(board.SCL, board.SDA)
    try:
        ads = ADS.ADS1015(i2c)
        ads.gain = ganancia
        entrada = AnalogIn(ads, getattr(ADS, 'P' + str(canal)))
        return i2c, entrada
    except Exception:
        i2c.deinit()
        raise


def scale_adc(x,zeroraw,spanraw,zero,span):

    zeroraw,spanraw,zero,span = map (lambda x: float(x), [zeroraw,spanraw,zero,span])

    y = ((span-zero)/(spanraw-zeroraw))*(x-zeroraw)+zero

    y = float(int(y*100))/100
    return y



def leer_nivel(entrada, calibracion):
    crudo = entrada.value
    if isinstance(crudo, bool) or not math.isfinite(crudo) or not 0 <= crudo <= 32767:
        raise ValueError('Lectura ADC fuera de rango: ' + repr(crudo))
    return scale_adc(crudo, *calibracion)


if __name__ == '__main__':
    import board
    import busio
    import adafruit_ads1x15.ads1015 as ADS
    from adafruit_ads1x15.analog_in import AnalogIn
    '''
    Definiciones de pines asociados al adc
    El parametro corresponde al canal del ADC
    '''
    # Create the I2C bus
    i2c = busio.I2C(board.SCL, board.SDA)
    
    # Create the ADC object using the I2C bus
    ads = ADS.ADS1015(i2c)
    
    
    # Create single-ended input on channel 0
    chan0 = AnalogIn(ads, ADS.P0)
    chan1 = AnalogIn(ads, ADS.P1)
    chan2 = AnalogIn(ads, ADS.P2)
    chan3 = AnalogIn(ads, ADS.P3)
    
    
    ads.gain = 2

    ##
    while True:
       
        print("-"*50)
        print("WIND DIRECTION: %s" % chan0.value)
        print("RADIATIONS: %s" % chan1.value)
        print("NIVEL: %s" % chan2.value)
        print("ANALOG_INPUT_3: %s" % chan3.value)
            
        time.sleep(1)