# Adapta el punto de selección del bootloader de ESP-IDF v4.4.7.
set(origen "${IDF_PATH}/components/bootloader/subproject/main")
set(salida "${CMAKE_CURRENT_BINARY_DIR}/bootloader_start_glima.c")
file(READ "${origen}/bootloader_start.c" original)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${origen}/bootloader_start.c")
set(punto "    return selected_boot_partition(bs);")
string(FIND "${original}" "${punto}" ubicacion)
if(ubicacion EQUAL -1)
    message(FATAL_ERROR "No se reconoce el bootloader de ESP-IDF. Use v4.4.7.")
endif()
string(REPLACE "${punto}" [=[
    if (glima_arrancar_xbee(bs)) {
        return TEST_APP_INDEX;
    }

    // En modo NORMAL, conservar la selección OTA y excluir XBee como rescate.
    bs->test.offset = 0;
    bs->test.size = 0;
    return selected_boot_partition(bs);]=] modificado "${original}")
file(WRITE "${salida}" "#include \"seleccion.h\"\n${modificado}")
idf_component_register(SRCS "${salida}" "seleccion.c"
    INCLUDE_DIRS "." REQUIRES bootloader bootloader_support PRIV_REQUIRES spi_flash)
target_include_directories(${COMPONENT_LIB} PRIVATE "${origen}")
set(scripts "${origen}/ld/esp32/bootloader.ld" "${origen}/ld/esp32/bootloader.rom.ld")
target_linker_script(${COMPONENT_LIB} INTERFACE "${scripts}")
target_link_libraries(${COMPONENT_LIB} INTERFACE "-u bootloader_hooks_include")
