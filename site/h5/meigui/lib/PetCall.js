/**
 * @file PetCall.js
 * @encode urf-8
 * @des 宝宝用到的相关接口，抽象出来，不放到玫瑰园首页里面
 * @author byronchen
 * @version 1.0
 * @date 2014-3-6
 */

function get_pet_by_id(pet_id)
{
    if (__pet_config)
    {
        return __pet_config["pet_" + pet_id];
    }
    else
    {
        return null;
    }
}

function getPet(avatarid)
{
    var pet_category = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z',
        'B1', 'B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B9', 'B10', 'B11', 'B12', 'B13', 'B14', 'B15', 'B16', 'B17', 'B18', 'B19', 'B20'];

    var petcfg = get_pet_by_id(avatarid);
    //alert("id:" + avatarid + "     config:" + __pet_config + "    petconfig:" + petcfg);
    if (null == petcfg)
    {
        return;
    }
    else
    {
        //var img_src = PetConfigParser.getPetGif(avatarid);
        var petName = encodeURIComponent(petcfg['name']);
        var skill = encodeURIComponent(petcfg['skill']);
        //var returnArray = [img_src, petName, petcfg['lvl'], petcfg['dex'], petcfg['price'], petcfg['skill1_prob'], petcfg['skill2_prob'], skill, petcfg['life'], petcfg['cate']];
        var returnArray = ['', petName, petcfg['lvl'], petcfg['dex'], petcfg['price'], petcfg['skill1_prob'], petcfg['skill2_prob'], skill, petcfg['life'], petcfg['cate']];
        return returnArray;
    }
}